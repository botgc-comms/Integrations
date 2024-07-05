
# Sync with IG - Azure Function for Syncing Golf Club Contacts with Mailchimp

## Project Description

This project contains a Python script that synchronizes contacts from a golf club's CRM with an audience in Mailchimp. The script is designed to run as an Azure Function and uses Terraform for infrastructure management. The setup includes secure handling of sensitive information using Azure Key Vault and GitHub Secrets.

## Prerequisites

Before you begin, ensure you have the following prerequisites:

- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
- [Terraform](https://www.terraform.io/downloads)
- [GitHub CLI](https://cli.github.com/) or Git configured for your repository
- An Azure account with appropriate permissions
- Python 3.8 or later

## Setup Instructions

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/your-repo-name.git
cd your-repo-name
```

### Step 2: Set Up Azure Resources with Terraform

#### 1. Initialize Terraform

```bash
terraform init
```

#### 2. Apply Terraform Configuration

Ensure you have the following environment variables set up for the Terraform run:

- `ARM_CLIENT_ID`
- `ARM_CLIENT_SECRET`
- `ARM_SUBSCRIPTION_ID`
- `ARM_TENANT_ID`
- `TF_VAR_member_id`
- `TF_VAR_member_pin`
- `TF_VAR_admin_password`
- `TF_VAR_mailchimp_api_key`

You can set these in your shell or add them to your GitHub Secrets for automated workflows.

```bash
terraform apply -auto-approve
```

### Step 3: Configure GitHub Actions

#### 1. Add Secrets to GitHub Repository

Go to your GitHub repository, then navigate to **Settings > Secrets and variables > Actions** and add the following secrets:

- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TENANT_ID`
- `MEMBER_ID`
- `MEMBER_PIN`
- `ADMIN_PASSWORD`
- `MAILCHIMP_API_KEY`
- `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`

#### 2. Verify GitHub Actions Workflow

Ensure that the `.github/workflows` directory contains the following workflow files:

- `deploy-terraform.yml`
- `deploy-function.yml`

### Step 4: Python Environment Setup

#### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 2. Run the Script Locally (Optional)

You can run the script locally for testing purposes:

```bash
python sync_with_ig.py
```

## Usage

### Automatic Deployment

Every push to the `main` branch will trigger GitHub Actions workflows to deploy the Terraform infrastructure and update the Azure Function.

### Manual Execution

You can manually trigger the function or deploy updates through the Azure Portal or using the Azure CLI.

## Project Structure

```plaintext
.
├── .github
│   └── workflows
│       ├── deploy-terraform.yml
│       └── deploy-function.yml
├── main.tf
├── requirements.txt
├── sync_with_ig.py
├── variables.tf
└── terraform.tfvars (do not commit real values)
```

## Security

- **Secrets Management**: Secrets are managed using Azure Key Vault and GitHub Secrets to ensure sensitive information is not exposed in the codebase.
- **Terraform State**: Use a remote backend to securely store Terraform state files.

## Contributing

We welcome contributions! Please follow these steps to contribute:

1. Fork the repository.
2. Create a new feature branch (`git checkout -b feature-branch`).
3. Commit your changes (`git commit -m 'Add new feature'`).
4. Push to the branch (`git push origin feature-branch`).
5. Open a pull request.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Contact

If you have any questions, feel free to contact the project maintainers.

---

Happy syncing!
