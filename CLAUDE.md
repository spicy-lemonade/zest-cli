# CLAUDE.md

## Important Rules

- *Never* run git commands without asking for user permission, even if 'auto-accept' is selected during a Claude Command session.
- *Never* run `terraform apply` or `terraform destroy` without explicit user permission.
- *Never* modify infrastructure state or cloud resources without asking for user permission.
- *Never* make assumptions. Ask for more information and wait for the user response.
- Do *not* use numerical prefixes when writing comments.
- Use double quotation marks instead of single quotation marks when possible.
- Favor modular, reusable code.
- Keep Files Small. A single source file should generally not exceed a few hundred lines. If a file grows beyond this size, it is a strong signal to split it along clear conceptual or responsibility boundaries into multiple files.


## Project Overview

This repository contains the infrastructure code for a machine learning project that trains locally-running small language models (SLMs) to translate natural language into CLI commands. The infrastructure provisions and manages cloud resources using Terraform and implements backend services in Python.

**Key Technologies:**
- Terraform for infrastructure as code
- Python for backend services
- Google Cloud Platform (GCP) as the cloud provider

### The Principle of Least Abstraction

Your goal is clarity over cleverness. Start with the simplest possible solution.

- **Default to a Single Function** - Solve the problem within a single function first. Do not create helper functions, new types, or new packages prematurely.
- **Justify Every Abstraction** - Before creating a new function, struct, or package, justify its existence based on concrete needs (e.g., function length, parameter count, or the Rule of Three).

### Function Design

Functions are the fundamental building blocks. They must be clear and focused.

- **Functions Do One Thing** - Every function should have a single, clear responsibility. If you cannot describe what a function does in one simple sentence, it's doing too much.
- **Function Length Limit** - A function should rarely exceed 50 lines. If a function grows longer, decompose it into smaller, private helper functions. Keep these helpers in the same file to maintain locality.
- **Parameter Limit** - A function must not have more than four parameters.
  - If you need more, group related parameters into a struct.
  - If a function needs to operate on shared state, make it a method on a struct that holds that state.
- **Return Values** - Return one or two values directly. If you need to return three or more related values, use a named struct to give them context and clarity.

### Duplication vs. Abstraction

Avoid hasty abstractions. Duplication is often better than the wrong abstraction.

- **The Rule of Three** - Do not refactor duplicated code on its first or second appearance. Only when you encounter the third instance should you consider creating a shared abstraction.
- **Verify True Duplication** - Before refactoring, confirm the duplicated code represents the same core logic. If the code blocks look similar by coincidence but handle different business rules that might change independently, they must remain separate.

### Package and Interface Philosophy

- **Packages Have a Singular Purpose** - A package should represent a single concept (e.g., `storage`, `auth`, `models`). Do not create generic "utility," "common," or "helpers" packages.
- **Interfaces are Defined by the Consumer** - Do not define large, monolithic interfaces on the producer side. Instead, the function that uses a dependency should define a small interface describing only the behavior it requires.
- **Keep Interfaces Small** - An interface should ideally have one method. Interfaces with more than three methods are a red flag and should be re-evaluated.

### Error Handling

- **Always Check Errors** - Never ignore returned errors. Handle them explicitly or propagate them with context.
- **Add Context to Errors** - When propagating errors, wrap them with `fmt.Errorf("context: %w", err)` to provide context about where and why the error occurred.
- **Return Errors, Don't Panic** - Reserve `panic` for truly unrecoverable situations. Prefer returning errors for expected failure modes.

### Naming Conventions

- **Short, Clear Names** - Variables should have short names in small scopes (e.g., `i` for loop indices, `err` for errors) and longer, more descriptive names in broader scopes.
- **Avoid Stuttering** - Don't repeat the package name in type names (e.g., use `storage.Bucket`, not `storage.StorageBucket`).
- **Exported vs. Unexported** - Use capitalization to control visibility. Export only what needs to be public.

## Terraform Standards

Infrastructure code should be predictable, maintainable, and follow Terraform best practices.

### Module Organization

- **Single Responsibility** - Each Terraform module should provision resources for a single logical component (e.g., `storage`, `networking`, `compute`).
- **Keep Modules Focused** - A module should not exceed ~300 lines. If it grows larger, split it into sub-modules.
- **Use Variables for Flexibility** - Parameterize values that might change across environments (e.g., region, instance size, bucket names).

### Resource Naming

- **Consistent Naming Convention** - Use a consistent pattern like `{project}-{environment}-{resource}-{identifier}` (e.g., `nlcli-prod-gcs-training-data`).
- **Use Variables for Names** - Define naming conventions in variables to ensure consistency across resources.

### State Management

- **Remote State** - Always use remote state (e.g., GCS backend) for collaboration and state locking.
- **Never Commit State Files** - Ensure `.tfstate` files are in `.gitignore`.
- **Separate State per Environment** - Use separate state files for different environments (dev, staging, prod).

### Code Quality

- **Format Code** - Always run `terraform fmt` before committing.
- **Validate Configuration** - Run `terraform validate` to catch syntax errors.
- **Plan Before Apply** - Always review `terraform plan` output before applying changes.

### Terraform Testing
```bash
# Validate syntax
terraform validate

# Check formatting
terraform fmt -check

# Plan to preview changes
terraform plan
```

## Project Structure
```
.
├── functions/         # Python backend (Firebase Cloud Functions)
├── terraform/         # Infrastructure as code
├── zest_cli/          # CLI application
├── firebase.json      # Firebase configuration
├── .firebaserc        # Firebase project settings
├── CLAUDE.md          # AI assistant guidance
├── README.md          # Project documentation
└── IMPLEMENTATION_SUMMARY.md  # Implementation details
```

## Project Notes

- All GCS buckets have versioning enabled except the models bucket
- Use environment variables for sensitive configuration (never commit secrets)