```markdown
# nexdexdown Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns used in the `nexdexdown` Python repository. It covers file naming conventions, import/export styles, commit message standards, and testing patterns. By following these guidelines, contributors can maintain consistency and quality throughout the codebase.

## Coding Conventions

### File Naming
- Use **camelCase** for all file names.
  - **Example:** `dataLoader.py`, `apiClient.py`

### Import Style
- Use **relative imports** within the package.
  - **Example:**
    ```python
    from .utils import parseData
    from ..models import UserModel
    ```

### Export Style
- Use **named exports** (explicitly define what is exported).
  - **Example:**
    ```python
    __all__ = ['parseData', 'formatOutput']
    ```

### Commit Messages
- Use **conventional commits** with the `feat` prefix for features.
- Keep commit messages concise (average 50 characters).
  - **Example:**  
    ```
    feat: add user authentication to apiClient
    ```

## Workflows

### Adding a New Feature
**Trigger:** When implementing a new feature.
**Command:** `/add-feature`

1. Create a new camelCase Python file for the feature.
2. Use relative imports for dependencies.
3. Define named exports in `__all__`.
4. Write a test file named `featureName.test.py`.
5. Commit with a message like: `feat: add [feature description]`.

### Running Tests
**Trigger:** When verifying code changes.
**Command:** `/run-tests`

1. Locate test files matching `*.test.*`.
2. Run tests using the project's preferred test runner (framework not specified; use `pytest` or similar if unsure).
   - **Example:**  
     ```bash
     pytest
     ```
3. Review test results and fix any failures.

### Refactoring Code
**Trigger:** When improving or restructuring existing code.
**Command:** `/refactor-code`

1. Rename files to camelCase if needed.
2. Update imports to maintain relative paths.
3. Ensure all exports are named in `__all__`.
4. Update or add tests as necessary.
5. Commit with a message like: `feat: refactor [module name] for clarity`.

## Testing Patterns

- Test files follow the pattern `*.test.*` (e.g., `apiClient.test.py`).
- Test framework is not explicitly specified; use standard Python testing tools.
- Place tests alongside the modules they test or in a dedicated test directory.

**Example test file:**
```python
# apiClient.test.py
from .apiClient import fetchData

def test_fetch_data_returns_expected_result():
    result = fetchData('test_input')
    assert result == 'expected_output'
```

## Commands
| Command        | Purpose                                      |
|----------------|----------------------------------------------|
| /add-feature   | Scaffold and commit a new feature            |
| /run-tests     | Run all test files matching `*.test.*`       |
| /refactor-code | Refactor code and update conventions/tests   |
```
