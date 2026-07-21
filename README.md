## Services

| Service | Port | Description |
| Auth | 8001 | User registration, login, token validation |
| Inventory | 8002 | Item CRUD, owned per user |
| Trade | 8003 | Buy/sell items between users |
| Prometheus | 9090 | Scrapes /metrics every 15s |
| Grafana | 3000 | Real-time dashboards |
| Locust | 8089 | Load testing UI |

## Running Locally

**Prerequisites:** Docker, Docker Compose

```bash
git clone https://github.com/cheryl9/govtech-girlsintech.git
cd govtech-girlsintech

# Create .env file
cat > .env << 'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
AUTH_DB_NAME=authdb
INVENTORY_DB_NAME=inventorydb
TRADE_DB_NAME=tradedb
AUTH_SERVICE_URL=http://auth:8001
INVENTORY_SERVICE_URL=http://inventory:8002
AUTH_PORT=8001
INVENTORY_PORT=8002
TRADE_PORT=8003
DB_HOST=postgres
EOF

docker compose up --build -d
docker compose ps
```

Test the services:
```bash
# Register
curl -X POST http://localhost:8001/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret"}'

# Login
curl -X POST http://localhost:8001/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret"}'

# Interactive API docs
open http://localhost:8001/docs
open http://localhost:8002/docs
open http://localhost:8003/docs
```

## AWS Deployment (Terraform)

**Prerequisites:** AWS CLI configured, Terraform installed

```bash
cd terraform

# 1. Initialise
terraform init

# 2. Preview changes
terraform plan

# 3. Deploy (~10 minutes)
terraform apply

# 4. Get EC2 IP
terraform output ec2_public_ip

# 5. Tear down when done
terraform destroy
```

**What Terraform creates:**
- VPC with public and private subnets across 2 availability zones
- EC2 instance (t3.micro) with Docker pre-installed
- RDS PostgreSQL (db.t3.micro) in private subnet
- Security groups (EC2 open on 8001-8003, RDS only from EC2)
- IAM role for EC2 with ECR read access
- Elastic IP for stable public address

## Observability

**Prometheus** scrapes `/metrics` from all 3 services every 15 seconds.

**Grafana dashboards** include:
- Request rate per service
- 5xx error rate
- p95 request latency
- Login success vs failure
- Active sessions

Access Grafana at `http://YOUR_EC2_IP:3000` (admin/admin)

## Tech Stack

| Layer | Technology |
|---|---|
| Services | Python, FastAPI, uvicorn |
| Database | PostgreSQL (RDS on AWS) |
| Containerisation | Docker, Docker Compose |
| Infrastructure | Terraform, AWS (EC2, RDS, VPC) |
| Observability | Prometheus, Grafana, PromQL |
| Load Testing | Locust |