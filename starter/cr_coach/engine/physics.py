"""Evidence-backed corrections over the immutable pinned backend.

PRIMARY shows a central Hog approaching the bridge while targeting a Crown
Tower. The roster instead cuts across the central river. Use ground navigation
for this approach, preserving river jumps when pulled by a non-Crown building.
This does not calibrate jump duration, attack loading or complete game fidelity.
"""
from simulator.engine import BattleEngine
from simulator.navigation import plan_route, segment_is_walkable

PHYSICS_PROFILE = 'hog-crown-bridge-v1'


class CoachBattleEngine(BattleEngine):
    def _movement_waypoint(self, state, entity, target):
        arena = self.ruleset.arena
        opposite_bank = (
            entity.y_mtile >= arena.river_y_min_mtile and target.y_mtile < arena.river_y_min_mtile
        ) or (
            entity.y_mtile <= arena.river_y_max_mtile and target.y_mtile > arena.river_y_max_mtile
        )
        if entity.card_id != 'hog-rider' or target.kind != 'tower' or not opposite_bank:
            return super()._movement_waypoint(state, entity, target)
        start = (entity.x_mtile, entity.y_mtile)
        goal = (target.x_mtile, target.y_mtile)
        radius = self._collision_radius(entity)
        obstacles = self._navigation_obstacles(state, target.uid)
        valid = (
            entity.navigation_target_uid == target.uid
            and entity.navigation_revision == state.navigation_revision
            and (entity.navigation_goal_x_mtile, entity.navigation_goal_y_mtile) == goal
        )
        if valid:
            while (entity.navigation_cursor < len(entity.navigation_waypoints)
                   and entity.navigation_waypoints[entity.navigation_cursor] == start):
                entity.navigation_cursor += 1
            if entity.navigation_cursor < len(entity.navigation_waypoints):
                waypoint = entity.navigation_waypoints[entity.navigation_cursor]
                if segment_is_walkable(arena, start, waypoint, agent_radius_mtile=radius,
                                       obstacles=obstacles):
                    return waypoint
        route = plan_route(arena, start, goal, agent_radius_mtile=radius, obstacles=obstacles)
        entity.navigation_waypoints = list(route[1:])
        entity.navigation_cursor = 0
        entity.navigation_target_uid = target.uid
        entity.navigation_revision = state.navigation_revision
        entity.navigation_goal_x_mtile, entity.navigation_goal_y_mtile = goal
        return entity.navigation_waypoints[0] if entity.navigation_waypoints else start
