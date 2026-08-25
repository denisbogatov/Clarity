"""Direct Clarity port of the foliage renormalizer incremental convex hull."""

from mathutils import Vector


def clarity_build_convex_hull(clarity_source_vertices):
    clarity_points = [Vector(clarity_point) for clarity_point in clarity_source_vertices]
    if len(clarity_points) < 4:
        return clarity_points, [(0, 1, 2)] if len(clarity_points) >= 3 else []

    clarity_i0 = min(range(len(clarity_points)), key=lambda clarity_index: clarity_points[clarity_index].x)
    clarity_i1 = max(range(len(clarity_points)), key=lambda clarity_index: clarity_points[clarity_index].x)
    if clarity_i0 == clarity_i1:
        return clarity_points, [(0, 1, 2)] if len(clarity_points) >= 3 else []

    clarity_best = -1.0
    clarity_i2 = 0
    for clarity_index, clarity_point in enumerate(clarity_points):
        if clarity_index in (clarity_i0, clarity_i1):
            continue
        clarity_area_sq = (
            (clarity_points[clarity_i1] - clarity_points[clarity_i0]).cross(
                clarity_point - clarity_points[clarity_i0]
            ).length_squared
        )
        if clarity_area_sq > clarity_best:
            clarity_best = clarity_area_sq
            clarity_i2 = clarity_index
    if clarity_best <= 1e-12:
        return clarity_points, [(0, 1, 2)] if len(clarity_points) >= 3 else []

    clarity_plane_normal = (
        clarity_points[clarity_i1] - clarity_points[clarity_i0]
    ).cross(
        clarity_points[clarity_i2] - clarity_points[clarity_i0]
    ).normalized()
    clarity_best = -1.0
    clarity_i3 = 0
    for clarity_index, clarity_point in enumerate(clarity_points):
        if clarity_index in (clarity_i0, clarity_i1, clarity_i2):
            continue
        clarity_distance = abs(clarity_plane_normal.dot(clarity_point - clarity_points[clarity_i0]))
        if clarity_distance > clarity_best:
            clarity_best = clarity_distance
            clarity_i3 = clarity_index
    if clarity_best <= 1e-12:
        return clarity_points, [(0, 1, 2)] if len(clarity_points) >= 3 else []

    clarity_interior = 0.25 * (
        clarity_points[clarity_i0]
        + clarity_points[clarity_i1]
        + clarity_points[clarity_i2]
        + clarity_points[clarity_i3]
    )
    clarity_faces = []

    def clarity_add_face(clarity_a, clarity_b, clarity_c):
        clarity_raw_normal = (
            clarity_points[clarity_b] - clarity_points[clarity_a]
        ).cross(clarity_points[clarity_c] - clarity_points[clarity_a])
        if clarity_raw_normal.length_squared <= 1e-20:
            return -1
        clarity_normal = clarity_raw_normal.normalized()
        clarity_d = -clarity_normal.dot(clarity_points[clarity_a])
        if clarity_normal.dot(clarity_interior) + clarity_d > 0.0:
            clarity_b, clarity_c = clarity_c, clarity_b
            clarity_raw_normal = (
                clarity_points[clarity_b] - clarity_points[clarity_a]
            ).cross(clarity_points[clarity_c] - clarity_points[clarity_a])
            clarity_normal = clarity_raw_normal.normalized()
            clarity_d = -clarity_normal.dot(clarity_points[clarity_a])
        clarity_faces.append({
            'vertices': (clarity_a, clarity_b, clarity_c),
            'normal': clarity_normal,
            'd': clarity_d,
            'valid': True,
            'outside': set(),
        })
        return len(clarity_faces) - 1

    clarity_add_face(clarity_i0, clarity_i1, clarity_i2)
    clarity_add_face(clarity_i0, clarity_i3, clarity_i1)
    clarity_add_face(clarity_i0, clarity_i2, clarity_i3)
    clarity_add_face(clarity_i1, clarity_i3, clarity_i2)

    def clarity_face_distance(clarity_face, clarity_point_index):
        return (
            clarity_face['normal'].dot(clarity_points[clarity_point_index])
            + clarity_face['d']
        )

    def clarity_most_visible(clarity_point_index, clarity_candidates=None):
        clarity_best_face = -1
        clarity_best_distance = 1e-6
        clarity_indices = (
            clarity_candidates if clarity_candidates is not None else range(len(clarity_faces))
        )
        for clarity_face_index in clarity_indices:
            clarity_face = clarity_faces[clarity_face_index]
            if not clarity_face['valid']:
                continue
            clarity_distance = clarity_face_distance(clarity_face, clarity_point_index)
            if clarity_distance > clarity_best_distance:
                clarity_best_distance = clarity_distance
                clarity_best_face = clarity_face_index
        return clarity_best_face

    for clarity_index in range(len(clarity_points)):
        if clarity_index in (clarity_i0, clarity_i1, clarity_i2, clarity_i3):
            continue
        clarity_face_index = clarity_most_visible(clarity_index)
        if clarity_face_index >= 0:
            clarity_faces[clarity_face_index]['outside'].add(clarity_index)

    def clarity_neighbor_faces(clarity_face_index):
        clarity_face_vertices = clarity_faces[clarity_face_index]['vertices']
        for clarity_u, clarity_v in (
                (clarity_face_vertices[0], clarity_face_vertices[1]),
                (clarity_face_vertices[1], clarity_face_vertices[2]),
                (clarity_face_vertices[2], clarity_face_vertices[0])):
            for clarity_other_index, clarity_other in enumerate(clarity_faces):
                if clarity_other_index == clarity_face_index or not clarity_other['valid']:
                    continue
                clarity_other_vertices = clarity_other['vertices']
                if clarity_u in clarity_other_vertices and clarity_v in clarity_other_vertices:
                    yield clarity_other_index

    while True:
        clarity_farthest_face = -1
        clarity_farthest_point = -1
        clarity_farthest_distance = 0.0
        for clarity_face_index, clarity_face in enumerate(clarity_faces):
            if not clarity_face['valid'] or not clarity_face['outside']:
                continue
            for clarity_point_index in clarity_face['outside']:
                clarity_distance = clarity_face_distance(clarity_face, clarity_point_index)
                if clarity_distance > clarity_farthest_distance:
                    clarity_farthest_distance = clarity_distance
                    clarity_farthest_face = clarity_face_index
                    clarity_farthest_point = clarity_point_index
        if clarity_farthest_face < 0:
            break

        clarity_visible = []
        clarity_stack = [clarity_farthest_face]
        clarity_visited = set()
        while clarity_stack:
            clarity_face_index = clarity_stack.pop()
            if clarity_face_index in clarity_visited:
                continue
            clarity_visited.add(clarity_face_index)
            clarity_face = clarity_faces[clarity_face_index]
            if not clarity_face['valid']:
                continue
            if clarity_face_distance(clarity_face, clarity_farthest_point) > 1e-6:
                clarity_visible.append(clarity_face_index)
                for clarity_neighbor in clarity_neighbor_faces(clarity_face_index):
                    if clarity_neighbor not in clarity_visited:
                        clarity_stack.append(clarity_neighbor)

        clarity_edge_counts = {}
        for clarity_face_index in clarity_visible:
            clarity_a, clarity_b, clarity_c = clarity_faces[clarity_face_index]['vertices']
            for clarity_edge in ((clarity_a, clarity_b), (clarity_b, clarity_c), (clarity_c, clarity_a)):
                clarity_edge = tuple(sorted(clarity_edge))
                clarity_edge_counts[clarity_edge] = clarity_edge_counts.get(clarity_edge, 0) + 1
        clarity_horizon = [
            clarity_edge for clarity_edge, clarity_count in clarity_edge_counts.items()
            if clarity_count == 1
        ]
        for clarity_face_index in clarity_visible:
            clarity_faces[clarity_face_index]['valid'] = False
        clarity_new_faces = []
        for clarity_a, clarity_b in clarity_horizon:
            clarity_face_index = clarity_add_face(clarity_a, clarity_b, clarity_farthest_point)
            if clarity_face_index >= 0:
                clarity_new_faces.append(clarity_face_index)
        for clarity_face_index in clarity_visible:
            for clarity_point_index in clarity_faces[clarity_face_index]['outside']:
                if clarity_point_index == clarity_farthest_point:
                    continue
                clarity_best_face = clarity_most_visible(clarity_point_index, clarity_new_faces)
                if clarity_best_face >= 0:
                    clarity_faces[clarity_best_face]['outside'].add(clarity_point_index)
            clarity_faces[clarity_face_index]['outside'].clear()

    clarity_vertices = []
    clarity_triangles = []
    for clarity_face in clarity_faces:
        if not clarity_face['valid']:
            continue
        clarity_base = len(clarity_vertices)
        clarity_vertices.extend(clarity_points[clarity_index].copy() for clarity_index in clarity_face['vertices'])
        clarity_triangles.append((clarity_base, clarity_base + 1, clarity_base + 2))
    return clarity_vertices, clarity_triangles
