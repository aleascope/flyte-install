from flytekit import task, workflow, ImageSpec
import pandas

@task
def add(a: int, b: int) -> int:    
    return a + b

@workflow
def my_workflow(a: int = 3, b: int = 4) -> int:
    return add(a=a, b=b)
