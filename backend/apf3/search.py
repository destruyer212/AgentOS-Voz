"""Busqueda de alternativas cuando un producto del menu esta agotado."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import ClassVar, TypeVar

State = TypeVar("State")


@dataclass(frozen=True)
class SearchResult:
    path: tuple[str, ...]
    cost: float
    expanded: int


class MenuAlternativeProblem:
    """Grafo sintetico de sustitutos del catalogo para un plato agotado."""

    initial_state = "Pollo a la Brasa"
    goal_state = "Pollo Ricky + Anticucho"
    graph: ClassVar[dict[str, list[tuple[str, float]]]] = {
        "Pollo a la Brasa": [("Mostro Olivar", 2), ("Pollo Olivar", 3)],
        "Mostro Olivar": [("Chaufa de Pollo", 2), ("Parrilla para Dos", 4)],
        "Pollo Olivar": [("Pollo Ricky + Anticucho", 2), ("Brochetas de Pollo", 3)],
        "Chaufa de Pollo": [("Aeropuerto", 1), ("Pollo Ricky + Anticucho", 4)],
        "Parrilla para Dos": [("Parrilla Familiar", 2)],
        "Brochetas de Pollo": [("Pollo Ricky + Anticucho", 1)],
        "Aeropuerto": [], "Pollo Ricky + Anticucho": [], "Parrilla Familiar": [],
    }

    def successors(self, state: str) -> Iterable[tuple[str, str, float]]:
        return ((name, name, cost) for name, cost in self.graph.get(state, []))

    def heuristic(self, state: str) -> float:
        estimates = {"Pollo a la Brasa": 3, "Mostro Olivar": 2, "Pollo Olivar": 1,
                     "Chaufa de Pollo": 3, "Parrilla para Dos": 3,
                     "Brochetas de Pollo": 1, "Aeropuerto": 4,
                     "Pollo Ricky + Anticucho": 0, "Parrilla Familiar": 5}
        return float(estimates[state])


def _result(path: list[str], cost: float, expanded: int) -> SearchResult:
    return SearchResult(tuple(path), cost, expanded)


def bfs(problem: MenuAlternativeProblem) -> SearchResult | None:
    queue = deque([(problem.initial_state, [], 0.0)])
    visited = {problem.initial_state}
    expanded = 0
    while queue:
        state, path, cost = queue.popleft()
        if state == problem.goal_state:
            return _result(path, cost, expanded)
        expanded += 1
        for action, next_state, _ in problem.successors(state):
            if next_state not in visited:
                visited.add(next_state)
                queue.append((next_state, path + [action], cost + _))
    return None


def dfs(problem: MenuAlternativeProblem) -> SearchResult | None:
    stack = [(problem.initial_state, [], 0.0)]
    visited = set()
    expanded = 0
    while stack:
        state, path, cost = stack.pop()
        if state in visited:
            continue
        visited.add(state)
        if state == problem.goal_state:
            return _result(path, cost, expanded)
        expanded += 1
        stack.extend((next_state, path + [action], cost + step)
                     for action, next_state, step in problem.successors(state))
    return None


def astar(problem: MenuAlternativeProblem) -> SearchResult | None:
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


def hill_climbing(problem: MenuAlternativeProblem) -> SearchResult | None:
    state = problem.initial_state
    path: list[str] = []
    cost = 0.0
    expanded = 0
    while state != problem.goal_state:
        expanded += 1
        candidates = list(problem.successors(state))
        if not candidates:
            return None
        action, next_state, step_cost = min(candidates, key=lambda item: problem.heuristic(item[1]))
        if problem.heuristic(next_state) >= problem.heuristic(state):
            return None
        state = next_state
        cost += step_cost
        path.append(action)
    return _result(path, cost, expanded)


SEARCH_ALGORITHMS: dict[str, Callable[[MenuAlternativeProblem], SearchResult | None]] = {
    "BFS": bfs,
    "DFS": dfs,
    "A*": astar,
    "Hill Climbing": hill_climbing,
}
