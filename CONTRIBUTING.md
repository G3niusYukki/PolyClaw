# Contributing to PolyClaw

Thank you for your interest in contributing to PolyClaw! This document provides guidelines and best practices for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Submitting Changes](#submitting-changes)
- [Security](#security)

---

## Code of Conduct

This project and everyone participating in it is governed by our commitment to:

- **Respect**: Treat all contributors with respect and professionalism
- **Collaboration**: Work together constructively towards common goals
- **Quality**: Strive for high-quality, maintainable code
- **Safety**: Prioritize safety, especially for financial components

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Git
- PostgreSQL 16 (for full testing) or SQLite (for development)
- [Optional] Docker and Docker Compose

### Setting Up Development Environment

1. **Fork and Clone**
   ```bash
   git clone https://github.com/YOUR_USERNAME/PolyClaw.git
   cd PolyClaw
   ```

2. **Create Virtual Environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Set Up Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run Tests**
   ```bash
   pytest
   ```

---

## Development Workflow

### Branch Naming

- `feature/description` — New features
- `bugfix/description` — Bug fixes
- `docs/description` — Documentation updates
- `refactor/description` — Code refactoring
- `test/description` — Test additions/improvements

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic changes)
- `refactor`: Code refactoring
- `test`: Test additions or changes
- `chore`: Build process or auxiliary tool changes

**Examples:**
```
feat(strategies): add momentum confirmation indicator

fix(execution): handle nonce collision in retry logic

docs(readme): update API endpoint documentation
```

---

## Code Standards

### Python Style Guide

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check code style
ruff check polyclaw/

# Auto-fix issues
ruff check --fix polyclaw/

# Format code
ruff format polyclaw/
```

Configuration in `pyproject.toml`:
- Line length: 100 characters
- Target Python version: 3.11

### Type Hints

Use type hints throughout the codebase:

```python
from typing import Optional, List, Dict

def process_market(
    market_id: str,
    confidence: float,
    tags: Optional[List[str]] = None
) -> Dict[str, any]:
    ...
```

Run type checking:
```bash
mypy polyclaw/
```

### Documentation Strings

Use Google-style docstrings:

```python
def calculate_position_size(
    edge: float,
    confidence: float,
    max_position: float
) -> float:
    """Calculate optimal position size using Kelly criterion.

    Args:
        edge: Expected edge as decimal (e.g., 0.05 for 5%)
        confidence: Probability of success (0.0 to 1.0)
        max_position: Maximum position size in USD

    Returns:
        Optimal position size in USD

    Raises:
        ValueError: If confidence is outside valid range
    """
    ...
```

---

## Testing

### Test Requirements

- All new code must include tests
- Maintain >= 80% code coverage
- Tests must pass before merging

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=polyclaw --cov-report=term-missing

# Run specific test file
pytest polyclaw/tests/test_strategies.py -v

# Run tests matching pattern
pytest -k "test_event_catalyst"

# Run live smoke tests (requires CTF_PRIVATE_KEY)
pytest -m live_manual
```

### Writing Tests

Use pytest with descriptive test names:

```python
def test_market_ranker_filters_low_liquidity_markets():
    """Test that markets with insufficient liquidity are filtered out."""
    market = create_market(liquidity_usd=500)  # Below threshold
    ranked = ranker.score([market])
    assert len(ranked) == 0
```

### Test Categories

- **Unit Tests**: Test individual functions/classes
- **Integration Tests**: Test component interactions
- **Live Tests**: Test with real APIs (manual, marked with `@pytest.mark.live_manual`)

---

## Documentation

### Code Documentation

- Add docstrings to all public functions and classes
- Include type hints in function signatures
- Document complex algorithms and business logic
- Add inline comments for non-obvious code

### User Documentation

Update relevant documentation when adding features:

- `README.md` — Overview and quick start
- `CLAUDE.md` — Development details
- `docs/` — Additional guides and runbooks

### API Documentation

API endpoints are automatically documented via FastAPI. Ensure:
- Descriptive endpoint summaries
- Detailed parameter descriptions
- Example request/response bodies

---

## Submitting Changes

### Pull Request Process

1. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make Changes**
   - Write code following style guidelines
   - Add tests for new functionality
   - Update documentation

3. **Run Quality Checks**
   ```bash
   # All checks must pass
   ruff check polyclaw/
   mypy polyclaw/
   pytest --cov=polyclaw
   ```

4. **Commit Changes**
   ```bash
   git add .
   git commit -m "feat(scope): description"
   ```

5. **Push and Create PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   Then create a Pull Request on GitHub.

### PR Description Template

```markdown
## Summary
Brief description of the changes

## Changes
- Change 1
- Change 2

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests pass (≥80% coverage)
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

### Review Process

- All PRs require at least one review
- Address review comments promptly
- Re-request review after making changes

---

## Security

### Reporting Security Issues

For security vulnerabilities, please email directly instead of opening a public issue:
- **Email**: [security contact - to be added]
- **Subject**: `[SECURITY] PolyClaw vulnerability report`

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Security Best Practices

When contributing:
- Never commit private keys, API keys, or passwords
- Use environment variables for sensitive configuration
- Validate all inputs
- Follow the principle of least privilege
- Be extra careful with execution-related code

---

## Questions?

- **General Questions**: [GitHub Discussions](https://github.com/G3niusYukki/PolyClaw/discussions)
- **Bug Reports**: [GitHub Issues](https://github.com/G3niusYukki/PolyClaw/issues)
- **Security Issues**: Email (see above)

Thank you for contributing to PolyClaw! 🚀
