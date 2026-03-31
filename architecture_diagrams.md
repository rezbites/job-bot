# Blulinked DEV — Architecture & Flow Diagrams
> Based on `infrastructure/cft-dev.yaml` and `.github/workflows/deploy-dev.yml`  
> Region: **us-west-2 (Oregon)** | Compute: **Single EC2 t3a.medium** running ECS on EC2 launch type

---

## Diagram 1 — Full Infrastructure Overview

This shows every AWS resource created by `cft-dev.yaml` and how they're connected.

```mermaid
graph TB
    subgraph Internet
        User["🌐 Internet / Users\nblulinked.in"]
        Dev["👨‍💻 Developer\nSSH :22"]
    end

    subgraph "AWS us-west-2 — VPC 10.0.0.0/16"
        IGW["🔀 Internet Gateway\nblulinked-dev-igw"]

        subgraph "Public Subnet A — 10.0.1.0/24 (us-west-2a)"
            EC2["🖥️ EC2 t3a.medium\n2 vCPU / 4 GB RAM\n30 GB gp3 EBS\nAMI: ECS-Optimized AL2023"]
            ASG["📊 Auto Scaling Group\nMin=Max=Desired=1\nblulinked-dev-asg"]
        end

        subgraph "Public Subnet B — 10.0.2.0/24 (us-west-2b)"
            RDS["🗄️ RDS PostgreSQL 16\ndb.t4g.micro\n20–40 GB gp3\nblulinked-dev-postgres"]
        end

        subgraph "EC2 — ECS Host Network"
            ECSCluster["ECS Cluster\nblulinked-dev-cluster"]

            subgraph "Frontend Task (host:80)"
                C_FE["📦 Container: frontend\nnginx:80\n256 MB"]
            end

            subgraph "Backend Task (host:8000-8002)"
                C_BE["📦 Container: backend\nFastAPI :8000\n1024 MB"]
                C_BR["📦 Container: brain\nLLM Interview :8001\n512 MB"]
                C_NS["📦 Container: nsfw\nNSFW ML :8002\n512 MB"]
            end
        end

        subgraph "Managed Services"
            ECR_FE["🐳 ECR\nblulinked-dev-frontend\nKeeps last 5 images"]
            ECR_BE["🐳 ECR\nblulinked-dev-backend\nKeeps last 5 images"]
            S3["🪣 S3 Bucket\nblulinked-dev-{acct}-us-west-2\nVersioned + AES256"]
            SM["🔐 Secrets Manager\n6 secrets (DB, JWT,\nSMTP, Groq, Twilio, Admin)"]
            CW["📋 CloudWatch Logs\n/ecs/blulinked-dev-frontend\n/ecs/blulinked-dev-backend\n3-day retention"]
        end

        S3EP["🔗 S3 VPC Gateway Endpoint\nFree — no NAT needed"]
    end

    subgraph "External APIs"
        Groq["🤖 Groq API\nllama-3.3-70b\nwhisper-large-v3"]
        Sarvam["🗣️ Sarvam AI\nbulbul:v3 TTS\nsaaras:v2 STT"]
        Twilio["📱 Twilio SMS"]
        Gmail["📧 Gmail SMTP"]
    end

    User -->|"HTTP :80"| IGW
    User -->|"HTTP :8000-8002"| IGW
    Dev -->|"SSH :22"| IGW
    IGW --> EC2
    EC2 --> RDS
    EC2 --> S3EP --> S3
    EC2 --> SM
    EC2 --> CW
    ECR_FE -->|"docker pull"| EC2
    ECR_BE -->|"docker pull"| EC2
    EC2 --> ECSCluster
    ECSCluster --> C_FE
    ECSCluster --> C_BE
    ECSCluster --> C_BR
    ECSCluster --> C_NS
    C_BE -->|"localhost:8001"| C_BR
    C_BE -->|"localhost:8002"| C_NS
    C_BR --> Groq
    C_BR --> Sarvam
    C_BE --> Twilio
    C_BE --> Gmail

    style EC2 fill:#FF9900,color:#000
    style ECSCluster fill:#FF9900,color:#000
    style RDS fill:#3F48CC,color:#fff
    style S3 fill:#7AA116,color:#fff
    style ECR_FE fill:#CC2264,color:#fff
    style ECR_BE fill:#CC2264,color:#fff
    style SM fill:#DD344C,color:#fff
    style Groq fill:#F55036,color:#fff
```

---

## Diagram 2 — CI/CD Pipeline: What Happens When You Push to `main`

This maps every job in `deploy-dev.yml` in order.

```mermaid
flowchart TD
    Push["⬆️ git push to main\n(or workflow_dispatch)"]

    Push --> J1

    subgraph J1["Job 1: ensure-infra (sequential, blocks all others)"]
        direction TB
        S1["📸 Snapshot EC2 instance ID + IP\n(before any changes)"]
        S2{"Does CloudFormation\nstack exist?"}
        S3_new["create-stack\nusing cft-dev.yaml\n+ all Parameters/Secrets"]
        S3_upd["update-stack\nusing cft-dev.yaml"]
        S3_skip["No changes\n→ skip"]
        S4["⏳ Wait for stack\ncreate/update complete"]
        S5{"EC2 instance ID\nchanged?"}
        S6["✅ Same instance\nIP is stable"]
        S7["❌ FAIL\nEC2 replaced!\nManual DNS update needed"]

        S1 --> S2
        S2 -->|"DOES_NOT_EXIST"| S3_new
        S2 -->|"CREATE/UPDATE_COMPLETE"| S3_upd
        S3_upd -->|"No updates"| S3_skip
        S3_new --> S4
        S3_upd --> S4
        S4 --> S5
        S5 -->|"Same"| S6
        S5 -->|"Different"| S7
    end

    J1 --> J2

    subgraph J2["Job 2: test (runs after ensure-infra)"]
        direction TB
        T1["✅ Check required files\n(Dockerfile, requirements.txt, etc.)"]
        T2["✅ Dockerfile syntax check\n(docker build --check)"]
        T3["✅ Frontend build check\n(npm ci + npm run build + dist check)"]
        T4["✅ Backend syntax check\n(py_compile main.py + config.py)"]
        T1 --> T2 --> T3 --> T4
    end

    J2 --> J3A & J3B

    subgraph J3A["Job 3a: build-backend (parallel)"]
        direction TB
        B1["Login to ECR"]
        B2["docker build -f Backend/Dockerfile\ntag: :sha + :latest"]
        B3["docker push to ECR\nblulinked-dev-backend"]
        B4["Output: image_uri"]
        B1 --> B2 --> B3 --> B4
    end

    subgraph J3B["Job 3b: build-frontend (parallel)"]
        direction TB
        F1["Login to ECR"]
        F2["Get EC2 public IP\nfrom ASG"]
        F3["docker build with VITE_API_BASE_URL=http://EC2_IP:8000\nVITE_BRAIN_API_URL=http://EC2_IP:8001\nVITE_WS_URL=ws://EC2_IP:8000"]
        F4["docker push to ECR\nblulinked-dev-frontend"]
        F5["Output: image_uri"]
        F1 --> F2 --> F3 --> F4 --> F5
    end

    J3A & J3B --> J4 & J4B

    subgraph J4["Job 4: deploy (runs after build jobs)"]
        direction TB
        D1["Fetch current backend task def JSON"]
        D2["jq: replace image for backend+brain+nsfw\nall 3 containers use same ECR image\n(SERVICE env var picks the process)"]
        D3["Register new task definition revision"]
        D4["ecs update-service backend\n--desired-count 1\n--force-new-deployment"]
        D5["Fetch current frontend task def JSON"]
        D6["jq: replace frontend container image"]
        D7["Register new frontend task revision"]
        D8["ecs update-service frontend\n--desired-count 1"]

        D1 --> D2 --> D3 --> D4
        D4 --> D5 --> D6 --> D7 --> D8
    end

    subgraph J4B["Job 4b: vulnerability-scan (parallel, non-blocking)"]
        direction TB
        VS1["Install Trivy scanner"]
        VS2["Scan backend image\n(CRITICAL only, exit-code 0)"]
        VS3["Scan frontend image\n(CRITICAL only, exit-code 0)"]
        VS4["Full HIGH/MEDIUM report\n(informational only)"]
        VS1 --> VS2 --> VS3 --> VS4
    end

    J4 --> J5

    subgraph J5["Job 5: verify (runs after deploy + ensure-infra)"]
        direction TB
        V1["⏳ Poll ECS services\nevery 30s up to 10min\nuntil running=desired, pending=0"]
        V2["Get final EC2 IP from ASG"]
        V3{"EC2 IP changed\nfrom pre-deploy?"}
        V4["❌ FAIL — DNS stale"]
        V5["✅ IP stable"]
        V6["Health checks with retries\n:80 → frontend\n:8000/health → backend\n:8001/health → brain\n:8002/health → nsfw (503 OK)"]
        V7["Smoke tests\nHTML served, /docs 200,\nJSON health, DNS check"]
        V8["📋 Print URLs + GitHub Step Summary"]

        V1 --> V2 --> V3
        V3 -->|"Changed"| V4
        V3 -->|"Same"| V5
        V5 --> V6 --> V7 --> V8
    end

    style Push fill:#2EA44F,color:#fff
    style J1 fill:#1F6FEB,color:#fff
    style J2 fill:#6F42C1,color:#fff
    style J3A fill:#E36209,color:#fff
    style J3B fill:#E36209,color:#fff
    style J4 fill:#CF222E,color:#fff
    style J5 fill:#1A7F37,color:#fff
```

---

## Diagram 3 — Runtime Request Flow (Internet → EC2 → Services → S3/RDS)

How a real user request travels through the system after deployment.

```mermaid
sequenceDiagram
    actor User as 🌐 User Browser
    participant DNS as DNS (blulinked.in)
    participant EC2 as 🖥️ EC2 Instance (Public IP)
    participant FE as 📦 Frontend Container :80
    participant BE as 📦 Backend Container :8000
    participant BR as 📦 Brain Container :8001
    participant NS as 📦 NSFW Container :8002
    participant RDS as 🗄️ RDS PostgreSQL
    participant S3 as 🪣 S3 Bucket
    participant Groq as 🤖 Groq API
    participant Sarvam as 🗣️ Sarvam AI

    Note over User, Sarvam: Scenario A — User loads the web app
    User->>DNS: GET blulinked.in
    DNS-->>User: EC2 Public IP
    User->>EC2: HTTP GET :80
    EC2->>FE: Route to frontend container (host network)
    FE-->>User: HTML/CSS/JS (React SPA)

    Note over User, Sarvam: Scenario B — User makes an API call (e.g. login)
    User->>EC2: POST :8000/auth/login
    EC2->>BE: Route to backend container (host network)
    BE->>RDS: SELECT user WHERE email=...
    RDS-->>BE: User row + hashed password
    BE-->>User: JWT access token (200 OK)

    Note over User, Sarvam: Scenario C — User uploads a profile photo
    User->>EC2: POST :8000/api/users/avatar (multipart)
    EC2->>BE: Route to backend
    BE->>S3: PutObject (via VPC Gateway Endpoint, FREE)
    S3-->>BE: ETag / Object URL
    BE->>RDS: UPDATE users SET avatar_url=...
    BE-->>User: 200 OK + signed URL

    Note over User, Sarvam: Scenario D — User creates a post (NSFW screening)
    User->>EC2: POST :8000/api/posts
    EC2->>BE: Route to backend
    BE->>NS: POST localhost:8002/screen\n(text + image bytes)
    NS->>NS: Run unitary/toxic-bert (text)\nRun Falconsai/nsfw_image_detection (image)
    NS-->>BE: {tier: "safe", score: 0.12}
    BE->>RDS: INSERT posts (nsfw_tier=safe, is_published=true)
    BE-->>User: 201 Created

    Note over User, Sarvam: Scenario E — User starts AI interview (Brain service)
    User->>EC2: POST :8001/agent/start (or via :8000 proxy)
    EC2->>BR: Route to brain container
    BR->>RDS: INSERT interview_session
    BR->>Groq: Chat completion (llama-3.3-70b-versatile)
    Groq-->>BR: Generated question
    BR-->>User: {"question": "Tell me about your experience with..."}

    Note over User, Sarvam: Scenario F — User sends voice reply in interview
    User->>EC2: POST :8001/agent/audio (WAV file)
    EC2->>BR: Route to brain
    BR->>Groq: audio.transcriptions.create (whisper-large-v3)
    Groq-->>BR: Transcript text
    BR->>Groq: analyze_response (llama-3.3-70b)
    Groq-->>BR: Extracted JSON data
    BR->>Sarvam: text_to_speech (bulbul:v3)
    Sarvam-->>BR: Base64 WAV audio
    BR-->>User: {"audio": "...", "next_question": "..."}
```

---

## Diagram 4 — Container Communication Inside EC2 (Host Networking)

All 4 containers share the EC2 host network. They all talk via `localhost`.

```mermaid
graph LR
    subgraph EC2["🖥️ EC2 Instance — Host Network (10.0.1.x public IP)"]
        subgraph Frontend_Task["ECS Frontend Task\n(NetworkMode: host)"]
            FE["📦 frontend\nnginx\nPort :80\n256 MB RAM"]
        end

        subgraph Backend_Task["ECS Backend Task\n(NetworkMode: host)"]
            BE["📦 backend\nFastAPI\nPort :8000\n1024 MB RAM\nSERVICE=api"]
            BR["📦 brain\nFastAPI\nPort :8001\n512 MB RAM\nSERVICE=brain"]
            NS["📦 nsfw\nFastAPI\nPort :8002\n512 MB RAM\nSERVICE=nsfw"]
        end

        ECSAgent["ECS Agent\n(manages containers)"]
    end

    subgraph Shared_Localhost["Shared Host Network — all ports are EC2's public ports"]
        P80[":80"]
        P8000[":8000"]
        P8001[":8001"]
        P8002[":8002"]
    end

    Internet["🌐 Internet"]
    ECR["🐳 ECR\nblulinked-dev-backend:sha"]
    SM["🔐 Secrets Manager"]
    CW["📋 CloudWatch"]
    RDS["🗄️ RDS :5432"]
    S3["🪣 S3"]

    Internet -->|"HTTP :80"| P80 --> FE
    Internet -->|"HTTP :8000"| P8000 --> BE
    Internet -->|"HTTP :8001"| P8001 --> BR
    Internet -->|"HTTP :8002"| P8002 --> NS

    BE -->|"localhost:8001\nBRAIN_UPSTREAM_URL"| BR
    BE -->|"localhost:8002\nNSFW_UPSTREAM_URL"| NS

    BE --> RDS
    BR --> RDS
    NS --> RDS

    BE --> S3
    NS --> S3

    ECR -->|"docker pull on task start"| ECSAgent
    ECSAgent --> BE & BR & NS & FE
    SM -->|"inject secrets at startup"| BE & BR & NS
    BE & BR & NS & FE -->|"stdout logs"| CW

    Note1["⚠️ Same physical image pulled\nfrom ECR for backend+brain+nsfw\nSERVICE env var selects entrypoint"]

    style BE fill:#FF9900,color:#000
    style BR fill:#1F6FEB,color:#fff
    style NS fill:#CF222E,color:#fff
    style FE fill:#2EA44F,color:#fff
    style EC2 fill:#232F3E,color:#fff
    style Internet fill:#0F62FE,color:#fff
```

---

## Key Facts Summary

| Aspect | Detail |
| :--- | :--- |
| **Region** | us-west-2 (Oregon) |
| **Compute** | 1× EC2 t3a.medium (2 vCPU, 4 GB, 30 GB EBS gp3) |
| **Networking** | ECS `host` network mode — all containers share EC2's IP |
| **Backend images** | All 3 backend containers (`backend`, `brain`, `nsfw`) use the **same ECR image** — `SERVICE` env var selects which process to start |
| **EC2 IP stability** | ASG min=max=1, no IP recycling — `deploy-dev.yml` checks that instance ID doesn't change between jobs and fails loudly if it does |
| **S3 Access** | Free via VPC Gateway Endpoint — no data transfer cost |
| **Secrets** | Injected at container startup via ECS Secrets from Secrets Manager |
| **Logs** | 3-day CloudWatch retention (dev cost saving) |
| **ECR Lifecycle** | Keep last 5 images only (dev reduces storage cost) |
