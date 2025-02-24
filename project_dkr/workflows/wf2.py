from flytekit import task, workflow
import pandas as pd
from typing import List

@task
def tabulate(a: int, b: int) -> List[int]:
    nb_rows = 10
    df = pd.DataFrame({
        'a': [a] * nb_rows,
        'b': [b] * nb_rows
    })
    df['c'] = df['a'] + df['b']
    return list(df['c'])

@task
def sum_table(l: List[int]) -> int:
    return int(sum(l))

@workflow
def my_workflow(a: int = 3, b: int = 4) -> int:
    df = tabulate(a=a, b=b)
    s = sum_table(df)
    return s
