#!/bin/bash
#
# Deploy Azure AI Foundry infrastructure for A2A Gateway integration.
#
# This script:
# 1. Validates prerequisites (Azure CLI, Terraform, Databricks CLI)
# 2. Gets the Databricks gateway URL automatically
# 3. Runs Terraform to deploy AI Foundry resources
# 4. Outputs connection information
#
# Usage:
#   ./deploy.sh                    # Uses PREFIX from environment or defaults
#   PREFIX=myprefix ./deploy.sh    # Override prefix
#   ./deploy.sh --destroy          # Destroy resources
#
# To select a specific Azure subscription before deploying:
#   az account set --subscription "Your Subscription Name"
#   ./deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/../terraform"

# Configuration (can be overridden via environment)
PREFIX="${PREFIX:-marcin}"
LOCATION="${LOCATION:-eastus}"
AUTO_APPROVE="${AUTO_APPROVE:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed. Please install it first."
        exit 1
    fi
}

# -----------------------------------------------------------------------------
# Main Script
# -----------------------------------------------------------------------------

# Handle --destroy flag
if [[ "$1" == "--destroy" ]]; then
    log_info "Destroying Azure AI Foundry infrastructure..."
    cd "$TERRAFORM_DIR"
    if [ -f "terraform.tfstate" ]; then
        terraform destroy -auto-approve
        log_info "Azure resources destroyed."
    else
        log_warn "No Terraform state found. Nothing to destroy."
    fi
    exit 0
fi

echo "============================================================"
echo "  Azure AI Foundry A2A Infrastructure Deployment"
echo "============================================================"
echo ""

# Check prerequisites
log_info "Checking prerequisites..."
check_command "az"
check_command "terraform"
check_command "databricks"
check_command "jq"

# Verify Azure login
if ! az account show &> /dev/null; then
    log_error "Not logged into Azure. Run 'az login' first."
    exit 1
fi

# Verify Databricks CLI is configured
if ! databricks auth env &> /dev/null; then
    log_warn "Databricks CLI may not be configured. Trying to get gateway URL anyway..."
fi

# Get configuration
log_info "Configuration:"
echo "  PREFIX:   ${PREFIX}"
echo "  LOCATION: ${LOCATION}"
echo ""

# Get Databricks gateway URL
log_info "Getting Databricks gateway URL..."
DATABRICKS_GATEWAY_URL=$(databricks apps get "${PREFIX}-a2a-gateway" --output json 2>/dev/null | jq -r '.url' || echo "")

if [ -z "$DATABRICKS_GATEWAY_URL" ] || [ "$DATABRICKS_GATEWAY_URL" == "null" ]; then
    log_error "Could not get Databricks gateway URL."
    log_error "Make sure the gateway is deployed: make deploy-gateway PREFIX=${PREFIX}"
    exit 1
fi

log_info "Gateway URL: ${DATABRICKS_GATEWAY_URL}"

# Get subscription and tenant IDs
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
log_info "Subscription ID: ${SUBSCRIPTION_ID}"
log_info "Tenant ID: ${TENANT_ID}"

# Change to Terraform directory
cd "$TERRAFORM_DIR"

# Initialize Terraform
log_info "Initializing Terraform..."
terraform init -upgrade

# Create/update variables
log_info "Applying Terraform configuration..."

TERRAFORM_ARGS=(
    -var="subscription_id=${SUBSCRIPTION_ID}"
    -var="prefix=${PREFIX}"
    -var="location=${LOCATION}"
    -var="databricks_gateway_url=${DATABRICKS_GATEWAY_URL}"
    -var="tenant_id=${TENANT_ID}"
)

if [ "$AUTO_APPROVE" == "true" ]; then
    TERRAFORM_ARGS+=("-auto-approve")
fi

terraform apply "${TERRAFORM_ARGS[@]}"

echo ""
echo "============================================================"
echo "  Deployment Complete"
echo "============================================================"
echo ""

# Show outputs
log_info "Deployment outputs:"
terraform output

echo ""
log_info "Environment variables for SDK:"
terraform output -json environment_variables | jq -r 'to_entries | .[] | "export \(.key)=\"\(.value)\""'

echo ""
log_info "Next steps:"
echo "  1. Open AI Foundry Portal:"
echo "     $(terraform output -raw ai_foundry_portal_url)"
echo ""
echo "  2. Test the A2A connection:"
echo "     ./test-agent.sh"
echo ""
echo "  3. Register Databricks connection for AI Foundry agent:"
echo "     ./create-uc-connection.sh azure-foundry https://your-foundry-agent-endpoint"
