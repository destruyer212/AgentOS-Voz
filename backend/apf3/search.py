"""Algoritmos de busqueda sobre el problema academico de completar un pedido."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import TypeVar

State = TypeVar("State")


@dataclass(frozen=True)
class SearchResult:
    path: tuple[str, ...]
    cost: float
    expanded: int


class OrderCompletionProblem:
    """Estado como campos del pedido ya conocidos; acciones completan un campo."""

    fields = ("items", "fulfillment", "address", "payment", "confirmation")
    initial_state = frozenset({"items"})
    goal_state = frozenset(fields)

    def successors(self, state: frozenset[str]) -> Iterable[tuple[str, frozenset[str], float]]:
        prerequisites = {
            "fulfillment": {"items"},
            "address": {"items", "fulfillment"},
            "payment": {"items", "fulfillment"},
            "confirmation": {"items", "fulfillment", "payment"},
        }
        for field in self.fields:
            if field not in state and prerequisites.get(field, {"items"}) <= state:
                yield field, state | {field}, 1.0

    def heuristic(self, state: frozenset[str]) -> float:
        return float(len(self.goal_state - state))


def _result(path: list[str], cost: float, expanded: int) -> SearchResult:
    return SearchResult(tuple(path), cost, expanded)


def bfs(problem: OrderCompletionProblem) -> SearchResult | None:
    queue = deque([(problem.initial_state, [])])
    visited = {problem.initial_state}
    expanded = 0
    while queue:
        state, path = queue.popleft()
        if state == problem.goal_state:
            return _result(path, len(path), expanded)
        expanded += 1
        for action, next_state, _ in problem.successors(state):
            if next_state not in visited:
                visited.add(next_state)
                queue.append((next_state, path + [action]))
    return None


def dfs(problem: OrderCompletionProblem) -> SearchResult | None:
    stack = [(problem.initial_state, [])]
    visited = set()
    expanded = 0
    while stack:
        state, path = stack.pop()
        if state in visited:
            continue
        visited.add(state)
        if state == problem.goal_state:
            return _result(path, len(path), expanded)
        expanded += 1
        stack.extend((next_state, path + [action]) for action, next_state, _ in problem.successors(state))
    return None


def astar(problem: OrderCompletionProblem) -> SearchResult | None:
    serial = count()
    frontier = [(problem.heuristic(problem.initial_state), 0.0, next(serial), problem.initial_state, [])]
    best_cost = {problem.initial_state: 0.0}
    expanded = 0
    while frontier:
        _, cost, _, state, path = heappop(frontier)
        if cost != best_cost.get(state):
            continue
        if state == problem.goal_state:
            return _result(path, cost, expanded)
        expanded += 1
        for action, next_state, step_cost in problem.successors(state):
            new_cost = cost + step_cost
            if new_cost < best_cost.get(next_state, float("inf")):
                best_cost[next_state] = new_cost
                heappush(frontier, (new_cost + problem.heuristic(next_state), new_cost,
                                    next(serial), next_state, path + [action]))
    return None


def hill_climbing(problem: OrderCompletionProblem) -> SearchResult | None:
    state = problem.initial_state
    path: list[str] = []
    expanded = 0
    while state != problem.goal_state:
        expanded += 1
        candidates = list(problem.successors(state))
        if not candidates:
            return None
        action, next_state, _ = min(candidates, key=lambda item: problem.heuristic(item[1]))
        if problem.heuristic(next_state) >= problem.heuristic(state):
            return None
        state = next_state
        path.append(action)
    return _result(path, len(path), expanded)


SEARCH_ALGORITHMS: dict[str, Callable[[OrderCompletionProblem], SearchResult | None]] = {
    "BFS": bfs,
    "DFS": dfs,
    "A*": astar,
    "Hill Climbing": hill_climbing,
}
