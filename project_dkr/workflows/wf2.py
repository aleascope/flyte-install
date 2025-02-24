from flytekit import task, workflow
import pandas as pd


@task
def add(a: int, b: int) -> int:
    nb_rows = 10
    df = pd.DataFrame({
        'a': [a] * nb_rows,
        'b': [b] * nb_rows
    })
    df['c'] = df['a'] + df['b']
    return int(df['c'].sum())


@workflow
def my_workflow(a: int = 3, b: int = 4) -> int:
    return add(a=a, b=b)
