from flytekit import task, workflow

@task
def greeting_task(name: str) -> str:
    return f"Hello, {name}!"

@workflow
def greeting_wf(name: str) -> str:
    return greeting_task(name=name)

# Required for registration detection
if __name__ == "__main__":
    # Test execution locally
    print(greeting_wf(name="World"))
