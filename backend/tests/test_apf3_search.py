from apf3.search import SEARCH_ALGORITHMS, MenuAlternativeProblem


def test_all_search_algorithms_find_an_alternative_to_sold_out_dish():
    problem = MenuAlternativeProblem()

    for algorithm in SEARCH_ALGORITHMS.values():
        result = algorithm(problem)

        assert result is not None
        assert result.path[-1] == problem.goal_state
        assert result.path[0] in {"Mostro Olivar", "Pollo Olivar"}
        assert result.cost == sum(
            next(cost for name, cost in problem.graph[previous] if name == step)
            for previous, step in zip([problem.initial_state, *result.path[:-1]], result.path)
        )
        assert result.expanded > 0


def test_astar_finds_lowest_cost_substitution_route():
    result = SEARCH_ALGORITHMS["A*"](MenuAlternativeProblem())
    assert result is not None
    assert result.path == ("Pollo Olivar", "Pollo Ricky + Anticucho")
    assert result.cost == 5
