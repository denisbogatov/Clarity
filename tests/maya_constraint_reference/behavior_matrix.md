# Maya constraint behavior matrix

The first implemented node is `pointConstraint`. Other Maya constraint types remain
represented in DNA but are deliberately not evaluated until their individual golden
fixtures and channel solvers exist.

| Scenario | Expected channel behavior |
| --- | --- |
| One target | Constrained rotate pivot reaches the target rotate pivot in world space |
| Two equal targets | World target is the arithmetic mean of both target pivots |
| Weighted targets | Target positions are normalized by the sum of positive weights |
| Maintain offset | Initial constrained-to-target world offset is retained |
| Skip Y | X/Z translation are driven; authored Y remains unchanged |
| Disabled/zero influence | Authored channels pass through unchanged |
| Parent + negative scale | World result is converted through parent effect and OPM |
| OPM + shear | Translation solve uses the prefix inverse, not `object_to_world` inverse |

Constraint output is applied only to `ObjectRuntime::maya_transform.evaluated`.
`Object::maya_transform` remains the authored, serialized and animatable source.
