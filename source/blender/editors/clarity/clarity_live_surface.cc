/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup editors
 */

#include <algorithm>
#include <string>

#include "BLI_string.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_report.hh"

#include "DNA_object_types.h"

#include "ED_clarity.hh"
#include "ED_undo.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_enum_types.hh"

#include "WM_api.hh"
#include "WM_types.hh"
#include "wm_event_types.hh"

#include "clarity_runtime.hh"

namespace blender::ed::clarity {

enum class MakeLiveAction : int8_t {
  Set = 0,
  Add = 1,
  Remove = 2,
  Deactivate = 3,
  Reactivate = 4,
};

static bool live_surface_object_supported(const Object &object)
{
  /* Evaluated NURBS surfaces expose their tessellated mesh to Blender's face snap backend. */
  return ELEM(object.type, OB_MESH, OB_SURF);
}

static Vector<ClarityObjectRuntimeRef> live_surface_selection_get(const bContext *C,
                                                                  bool &r_had_selection)
{
  Vector<Object *> objects;
  CTX_DATA_BEGIN (C, Object *, object, selected_objects) {
    r_had_selection = true;
    if (live_surface_object_supported(*object)) {
      objects.append(object);
    }
  }
  CTX_DATA_END;

  /* Maya labels a multi-live set by the first-selected object. Blender does not retain a complete
   * selection chronology, but the active object is the user's most recent explicit selection and
   * is therefore the faithful first entry. */
  if (Object *active = CTX_data_active_object(C)) {
    const int64_t active_index = objects.as_span().first_index_try(active);
    if (active_index > 0) {
      objects.remove(active_index);
      objects.insert(0, active);
    }
  }

  Vector<ClarityObjectRuntimeRef> references;
  for (const Object *object : objects) {
    references.append(ED_clarity_object_runtime_ref_create(*object));
  }
  return references;
}

static wmOperatorStatus clarity_make_live_exec(bContext *C, wmOperator *op)
{
  ClarityLiveSurfaceRegistry *registry = live_surface_registry_ensure(C);
  if (registry == nullptr) {
    return OPERATOR_CANCELLED;
  }

  const MakeLiveAction action = MakeLiveAction(RNA_enum_get(op->ptr, "action"));
  bool had_selection = false;
  Vector<ClarityObjectRuntimeRef> selection;
  if (ELEM(action, MakeLiveAction::Set, MakeLiveAction::Add, MakeLiveAction::Remove)) {
    selection = live_surface_selection_get(C, had_selection);
  }

  if (had_selection && selection.is_empty()) {
    BKE_report(op->reports,
               RPT_ERROR,
               "Make Live supports polygon meshes and NURBS surface objects");
    return OPERATOR_CANCELLED;
  }
  if (ELEM(action, MakeLiveAction::Add, MakeLiveAction::Remove) && selection.is_empty()) {
    BKE_report(op->reports, RPT_ERROR, "Select at least one supported surface object");
    return OPERATOR_CANCELLED;
  }

  ED_clarity_live_surface_undo_begin(C);
  bool changed = registry->prune_invalid(*CTX_data_main(C));
  switch (action) {
    case MakeLiveAction::Set:
      changed = (selection.is_empty() ? registry->deactivate() : registry->set(selection)) ||
                changed;
      break;
    case MakeLiveAction::Add:
      changed = registry->add(selection) || changed;
      break;
    case MakeLiveAction::Remove:
      changed = registry->remove(selection) || changed;
      break;
    case MakeLiveAction::Deactivate:
      changed = registry->deactivate() || changed;
      break;
    case MakeLiveAction::Reactivate:
      changed = registry->reactivate() || changed;
      break;
  }

  if (!changed) {
    ED_clarity_undo_step_clear(C);
    return OPERATOR_CANCELLED;
  }
  live_surface_registry_changed(C);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus clarity_make_live_invoke(bContext *C,
                                                  wmOperator *op,
                                                  const wmEvent *event)
{
  if (RNA_enum_get(op->ptr, "action") == int(MakeLiveAction::Set)) {
    if (event != nullptr && event->type == MIDDLEMOUSE) {
      RNA_enum_set(op->ptr,
                   "action",
                   int(ED_clarity_live_surface_active(C) ? MakeLiveAction::Deactivate :
                                                          MakeLiveAction::Reactivate));
    }
    else if (const ClarityLiveSurfaceRegistry *registry = live_surface_registry_get(C)) {
      bool had_selection = false;
      const Vector<ClarityObjectRuntimeRef> selection = live_surface_selection_get(C,
                                                                                   had_selection);
      const bool same_set = had_selection && selection.size() == registry->active().size() &&
                            std::equal(selection.begin(),
                                       selection.end(),
                                       registry->active().begin(),
                                       [](const ClarityObjectRuntimeRef &a,
                                          const ClarityObjectRuntimeRef &b) {
                                         return a.session_uid == b.session_uid;
                                       });
      if (same_set) {
        RNA_enum_set(op->ptr, "action", int(MakeLiveAction::Deactivate));
      }
    }
  }
  return clarity_make_live_exec(C, op);
}

static bool clarity_make_live_poll(bContext *C)
{
  return CTX_wm_manager(C) != nullptr && CTX_data_main(C) != nullptr;
}

static std::string clarity_make_live_description(bContext *C,
                                                 wmOperatorType *ot,
                                                 PointerRNA * /*ptr*/)
{
  const ClarityLiveSurfaceRegistry *registry = live_surface_registry_get(C);
  if (registry == nullptr || registry->active().is_empty()) {
    return ot->description;
  }
  Main *bmain = CTX_data_main(C);
  std::string description = "Live surfaces: ";
  bool has_surface = false;
  for (const int64_t i : registry->active().index_range()) {
    const ClarityObjectRuntimeRef &reference = registry->active()[i];
    const Object *object = bmain != nullptr ?
                               ED_clarity_object_runtime_ref_resolve(*bmain, reference) :
                               nullptr;
    if (bmain != nullptr && object == nullptr) {
      continue;
    }
    if (has_surface) {
      description += ", ";
    }
    description += object != nullptr ? object->id.name + 2 : reference.id_name + 2;
    has_surface = true;
  }
  if (!has_surface) {
    return ot->description;
  }
  description += ". Click to replace from selection; middle-click toggles the recent set";
  return description;
}

static void CLARITY_OT_make_live(wmOperatorType *ot)
{
  static const EnumPropertyItem action_items[] = {
      {int(MakeLiveAction::Set),
       "SET",
       0,
       "Make Live",
       "Replace the live set with selected surfaces; with nothing selected, deactivate it"},
      {int(MakeLiveAction::Add),
       "ADD",
       0,
       "Add Selected",
       "Add selected surfaces to the live set"},
      {int(MakeLiveAction::Remove),
       "REMOVE",
       0,
       "Remove Selected",
       "Remove selected surfaces from the live set"},
      {int(MakeLiveAction::Deactivate),
       "DEACTIVATE",
       0,
       "Make Not Live",
       "Deactivate the live set while retaining it in history"},
      {int(MakeLiveAction::Reactivate),
       "REACTIVATE",
       0,
       "Make Live Again",
       "Reactivate the most recent live set"},
      {0, nullptr, 0, nullptr, nullptr},
  };

  ot->name = "Make Live";
  ot->description =
      "Make selected surfaces live so transforms and interactive creation project onto them";
  ot->idname = "CLARITY_OT_make_live";
  ot->invoke = clarity_make_live_invoke;
  ot->exec = clarity_make_live_exec;
  ot->get_description = clarity_make_live_description;
  ot->poll = clarity_make_live_poll;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
  RNA_def_enum(ot->srna, "action", action_items, int(MakeLiveAction::Set), "Action", "");
}

static const EnumPropertyItem *clarity_live_surface_history_itemf(bContext *C,
                                                                  PointerRNA * /*ptr*/,
                                                                  PropertyRNA * /*prop*/,
                                                                  bool *r_free)
{
  if (C == nullptr) {
    return rna_enum_dummy_NULL_items;
  }
  ClarityLiveSurfaceRegistry *registry = live_surface_registry_get(C);
  if (registry == nullptr || registry->history().is_empty()) {
    return rna_enum_dummy_NULL_items;
  }
  Main *bmain = CTX_data_main(C);

  EnumPropertyItem *items = nullptr;
  int items_num = 0;
  for (const int64_t i : registry->history().index_range()) {
    const Span<ClarityObjectRuntimeRef> set = registry->history()[i];
    if (set.is_empty()) {
      continue;
    }
    char identifier[32];
    char label[MAX_ID_NAME + 16];
    BLI_snprintf(identifier, sizeof(identifier), "HISTORY_%lld", static_cast<long long>(i));
    const ClarityObjectRuntimeRef *display_reference = &set.first();
    const Object *object = nullptr;
    if (bmain != nullptr) {
      display_reference = nullptr;
      for (const ClarityObjectRuntimeRef &reference : set) {
        if (Object *candidate = ED_clarity_object_runtime_ref_resolve(*bmain, reference)) {
          display_reference = &reference;
          object = candidate;
          break;
        }
      }
      if (display_reference == nullptr) {
        continue;
      }
    }
    const char *name = object != nullptr ? object->id.name + 2 : display_reference->id_name + 2;
    if (set.size() > 1) {
      BLI_snprintf(label,
                   sizeof(label),
                   "<%s...> (%lld)",
                   name,
                   static_cast<long long>(set.size()));
    }
    else {
      BLI_strncpy(label, name, sizeof(label));
    }
    const EnumPropertyItem item = {int(i), identifier, 0, label, "Activate this recent live set"};
    RNA_enum_item_add(&items, &items_num, &item);
  }
  RNA_enum_item_end(&items, &items_num);
  *r_free = true;
  return items;
}

static wmOperatorStatus clarity_live_surface_history_exec(bContext *C, wmOperator *op)
{
  ClarityLiveSurfaceRegistry *registry = live_surface_registry_get(C);
  if (registry == nullptr) {
    return OPERATOR_CANCELLED;
  }
  ED_clarity_live_surface_undo_begin(C);
  if (!registry->activate_history(RNA_enum_get(op->ptr, "entry"))) {
    ED_clarity_undo_step_clear(C);
    return OPERATOR_CANCELLED;
  }
  live_surface_registry_changed(C);
  return OPERATOR_FINISHED;
}

static void CLARITY_OT_live_surface_history(wmOperatorType *ot)
{
  ot->name = "Live Surface History";
  ot->description = "Activate a recent live-surface set";
  ot->idname = "CLARITY_OT_live_surface_history";
  ot->invoke = WM_menu_invoke;
  ot->exec = clarity_live_surface_history_exec;
  ot->poll = clarity_make_live_poll;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  PropertyRNA *prop = RNA_def_enum(
      ot->srna, "entry", rna_enum_dummy_NULL_items, 0, "Recent Live Surface", "");
  RNA_def_enum_funcs(prop, clarity_live_surface_history_itemf);
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_ENUM_NO_TRANSLATE);
  ot->prop = prop;
}

static void MAYA_OT_make_live(wmOperatorType *ot)
{
  CLARITY_OT_make_live(ot);
  ot->idname = "MAYA_OT_make_live";
}

static void MAYA_OT_live_surface_history(wmOperatorType *ot)
{
  CLARITY_OT_live_surface_history(ot);
  ot->idname = "MAYA_OT_live_surface_history";
}

void register_live_surface_operators()
{
  WM_operatortype_append(CLARITY_OT_make_live);
  WM_operatortype_append(CLARITY_OT_live_surface_history);
  WM_operatortype_append(MAYA_OT_make_live);
  WM_operatortype_append(MAYA_OT_live_surface_history);
}

}  // namespace blender::ed::clarity
