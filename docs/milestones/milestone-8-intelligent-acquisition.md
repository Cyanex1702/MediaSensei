# MediaSensei — Milestone 8: Intelligent Acquisition & Prompt-Based Discovery

## Implementation Prompt

You are the **lead software architect, principal engineer, and implementation owner** for this MediaSensei milestone.

This milestone adds a new first-class subsystem:

# Intelligent Acquisition

Its purpose is to let a user describe, configure, discover, acquire, validate, and iteratively collect internet-accessible media/data until a useful target is reached, while preserving MediaSensei's existing principles of local-first operation, reproducibility, provenance, data safety, extensibility, persistent jobs, and provider isolation.

This is a **standalone milestone**.

Do **not** merge it into the Dataset Provider milestone, Plugin SDK hardening milestone, or final packaging/release milestone.

Complete this milestone and its acceptance criteria before continuing to later milestones.

---

# 1. Milestone Position

This milestone belongs:

```text
Dataset Providers
Hugging Face + Kaggle
        ↓
INTELLIGENT ACQUISITION
Prompt-Based Discovery + Adaptive Acquisition
        ↓
Plugin Integration / Plugin SDK Finalization
        ↓
Plugin Hardening / Reliability
        ↓
Packaging / Release
```

The Hugging Face/Kaggle provider work should already exist before this milestone begins.

This milestone intentionally comes **before public plugin contracts are hardened/frozen**, because real Intelligent Acquisition implementation may reveal new provider contracts that the Plugin SDK must support.

The following plugin-facing abstractions may be introduced or refined during this milestone:

```text
DiscoveryProvider
SourceConnector
AcquisitionDownloader
PromptPlannerProvider
RelevanceEvaluator
```

Do not perform unrelated Plugin SDK hardening here.

The next plugin milestone should finalize the public contracts based on the real usage proven in this milestone.

---

# 2. Product Principle

The defining principle of this milestone is:

> **AI-enhanced, not AI-dependent.**

Also preserve this rule:

> **Do not turn missing capability into a dead end. Turn it into another path.**

MediaSensei must help users accomplish work using the capabilities available to them.

Do not design:

```text
No local LLM
→ feature disabled
```

Prefer:

```text
User Goal
   ↓
Determine available capabilities
   ↓
Choose an appropriate execution strategy
   ↓
Complete the work
```

Possible execution strategies may include:

```text
ordinary libraries
provider APIs
search APIs
HTTP
deterministic algorithms
lightweight local models
larger local models
approved remote AI
plugins
manual configuration
human review
```

AI is an enhancement layer.

It is not the foundation of acquisition.

---

# 3. Why This Milestone Exists

Traditional acquisition may be as simple as:

```text
query
→ search
→ collect URLs
→ download files
```

That workflow remains useful.

MediaSensei should modernize it into:

```text
goal
→ structured acquisition specification
→ discovery
→ candidate acquisition
→ validation
→ deduplication
→ quality evaluation
→ optional semantic relevance
→ acceptance / rejection
→ adaptive replenishment
→ accepted target
```

A user should be able to say:

```text
Get me 500 usable images of marine life.

Prefer real photographs.

Include:
- sharks
- whales
- dolphins
- sea turtles
- coral reefs
- octopus
- jellyfish
- tropical fish

Minimum resolution: 768×768.

Avoid:
- corrupt files
- duplicates
- near-duplicates
- illustrations where possible
- text-heavy images
- obviously irrelevant results
```

The important semantic meaning is:

```text
Target = 500 accepted usable assets
```

not:

```text
Target = download exactly 500 files
```

MediaSensei may need to discover or download more than 500 candidates in order to produce 500 accepted assets.

---

# 4. Scope Boundary

This milestone must implement a **complete image-first vertical slice** of Intelligent Acquisition.

The architecture must be multimodal.

Do not attempt to fully solve every modality with advanced AI during this milestone.

## Required end-to-end implementation

Images:

```text
prompt or manual specification
→ acquisition plan
→ discovery
→ candidate selection
→ download
→ validation
→ exact deduplication
→ near-duplicate analysis
→ quality gates
→ optional relevance evaluation
→ acceptance/rejection
→ adaptive replenishment
→ target completion
→ project catalog
→ provenance
```

## Required architecture readiness

Design contracts and target models so the same subsystem can later support:

```text
video
audio
documents/text
tabular/datasets
```

## Useful baseline support where existing MediaSensei capabilities already make it straightforward

It is acceptable to expose basic acquisition for other modalities using existing providers/connectors, such as:

```text
video:
search/provider result
→ yt-dlp/direct/provider acquisition where permitted
→ ffprobe validation
→ Asset

audio:
direct/provider acquisition
→ FFmpeg validation
→ Asset

documents:
URL/provider discovery
→ HTTP acquisition
→ parser validation
→ Asset/ContentUnit

datasets:
existing Hugging Face/Kaggle providers
→ import
```

Do not destabilize the milestone by attempting advanced semantic evaluation for every modality simultaneously.

---

# 5. Non-Goals

Do not build:

- a general autonomous browser agent;
- unrestricted web crawling;
- CAPTCHA solving or bypass;
- authentication bypass;
- stealth browser fingerprinting intended to evade blocking;
- scraping specifically designed to defeat explicit access controls;
- a distributed crawler cluster;
- a giant mandatory LLM dependency;
- a mandatory cloud AI dependency;
- a mandatory NVIDIA/GPU dependency;
- full multimodal semantic understanding for every media type;
- self-training acquisition agents;
- opaque AI decisions with no provenance;
- automatic permanent deletion of rejected media;
- automatic weakening of user quality requirements to hit a target;
- a provider-specific acquisition architecture.

Use official APIs where available and appropriate.

Respect source/provider terms, access controls, rate limits, and project policies.

---

# 6. Core Architecture

Implement Intelligent Acquisition as an application-layer subsystem built on top of existing MediaSensei primitives.

Conceptually:

```text
┌──────────────────────────────────────────────┐
│ Interfaces                                   │
│ React UI / REST / CLI / Python SDK           │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Acquisition Application Layer                │
│ Requests / Specs / Plans / Runs / Decisions  │
└──────────────────────┬───────────────────────┘
                       │
        ┌──────────────┼─────────────────┐
        ▼              ▼                 ▼
 Prompt Planner    Discovery Engine   Yield Controller
        │              │                 │
        └──────────────┼─────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Acquisition Pipeline                         │
│ Download / Validate / Dedup / Quality        │
│ Relevance / Accept / Reject                  │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Existing MediaSensei Core                    │
│ Source / Asset / Feature / Job / Pipeline    │
│ Quality / Content Addressing / Lineage       │
└──────────────────────────────────────────────┘
```

Do not duplicate existing Asset, Source, Feature, Job, PipelineRun, Quality, or content-addressed storage concepts.

---

# 7. Natural Language Must Compile to Structured Data

A natural-language prompt must **never directly control a downloader or scraper**.

Use:

```text
Natural language
      ↓
Prompt Planner
      ↓
AcquisitionSpec
      ↓
normal deterministic application logic
```

The structured `AcquisitionSpec` is the authoritative execution input.

The original prompt is provenance.

The user must be able to inspect and edit the generated specification before starting a large run.

The same `AcquisitionSpec` must also be creatable without AI through:

- React UI;
- REST API;
- CLI;
- Python SDK;
- structured/manual form.

---

# 8. New Domain/Application Concepts

Introduce clear models for the Intelligent Acquisition lifecycle.

## 8.1 AcquisitionRequest

Represents the user's original request.

Suggested fields:

```text
id
project_id
original_prompt
created_at
updated_at
created_by where applicable
status
```

The original prompt must be retained.

---

## 8.2 AcquisitionSpec

Normalized machine-readable description of the target.

Example:

```yaml
modality: image

target:
  unit: accepted_assets
  count: 500

topic:
  description: marine life

coverage:
  categories:
    - sharks
    - whales
    - dolphins
    - sea_turtles
    - coral_reefs
    - octopus
    - jellyfish
    - tropical_fish

requirements:
  min_width: 768
  min_height: 768

reject:
  corrupt: true
  exact_duplicates: true
  near_duplicates: true
  text_heavy: true
  low_quality: true

relevance:
  enabled: true
  strategy: auto

acquisition:
  replenish_until_target: true

limits:
  max_candidates: 1500
  max_download_bytes: null
  max_storage_bytes: null
  max_external_cost: null
```

Do not make every field mandatory.

Simple users need sensible defaults.

Advanced users need control.

---

## 8.3 AcquisitionPlan

An executable plan derived from the spec.

Suggested information:

```text
target
candidate estimate
queries
query groups
providers
provider priorities
budgets
validation gates
quality gates
relevance strategy
batch strategy
coverage strategy
estimated storage
external cost estimate where known
```

A plan must be inspectable before execution.

---

## 8.4 AcquisitionRun

Persistent execution of an AcquisitionPlan.

Suggested states:

```text
draft
planning
ready
discovering
acquiring
validating
replenishing
paused
completed
completed_with_shortfall
failed
cancelled
```

The run must survive process/application restart.

---

## 8.5 AcquisitionQuery

Persist generated or manually entered discovery queries.

Fields should include enough provenance to answer:

```text
Who/what generated this query?
Which provider used it?
How many candidates resulted?
How many candidates were accepted?
```

Suggested fields:

```text
query
origin
planner/provider
provider_id
priority
created_at
result_count
evaluated_count
accepted_count
```

---

## 8.6 AcquisitionCandidate

A discovered candidate is not yet an Asset.

```text
AcquisitionCandidate
       ↓ successful acquisition
Asset
```

Possible candidate states:

```text
discovered
shortlisted
rejected_preflight
queued
downloading
downloaded
validating
accepted
rejected
failed
```

Suggested candidate metadata:

```text
provider
remote_id
source_url
landing_page_url
preview_url
title
description
media_type
declared_dimensions
declared_duration
author
license where available
estimated_size
custom_metadata
```

---

## 8.7 AcquisitionDecision

Acceptance/rejection/review decisions must be explicit.

Possible decisions:

```text
ACCEPT
REJECT
REVIEW
```

Possible reason codes:

```text
LOW_RESOLUTION
CORRUPT
UNSUPPORTED_FORMAT
DUPLICATE_EXACT
DUPLICATE_NEAR
TEXT_HEAVY
LOW_QUALITY
IRRELEVANT
LICENSE_NOT_ALLOWED
SOURCE_LIMIT_REACHED
DOWNLOAD_FAILED
POLICY_BLOCKED
USER_REJECTED
OTHER
```

Never represent rejection only as an unexplained score.

---

# 9. Discovery and Acquisition Must Be Separate

Introduce or formalize:

```text
DiscoveryProvider
```

Discovery answers:

> What candidates exist?

Acquisition answers:

> Fetch this selected candidate.

Conceptual discovery interface:

```python
class DiscoveryProvider(Protocol):
    def capabilities(self) -> DiscoveryCapabilities:
        ...

    async def search(
        self,
        request: DiscoveryRequest,
    ) -> DiscoveryPage:
        ...
```

A `DiscoveryRequest` should support where appropriate:

```text
query
modality
filters
limit/page size
cursor
safe/provider-specific options
```

A discovery result should be metadata-first where possible.

Do not download full media simply to learn that it exists.

---

# 10. SourceConnector / AcquisitionDownloader

Use existing Source/Connection architecture.

Acquisition of a candidate may use:

```text
provider SDK/API
HTTP/httpx
gallery-dl where appropriate
yt-dlp where appropriate
dataset provider
specialized library
community plugin
```

Libraries are adapters.

They are not the architecture.

Bad:

```text
MediaSensei Core
→ hard-coded Bing library calls
```

Good:

```text
MediaSensei
→ DiscoveryProvider
→ provider/search/library adapter
```

A provider/library can disappear or change without forcing a domain rewrite.

---

# 11. Initial Discovery Provider Strategy

Do not permanently couple the product to one internet search engine.

Implement at least:

1. a deterministic/mock discovery provider used by tests;
2. one practical real image discovery implementation appropriate for the current repository/environment;
3. an adapter shape that allows additional search/provider plugins later.

Where provider credentials are needed, use the existing Connection/Credential system.

Do not place secrets inside AcquisitionSpec or project metadata.

If a practical external search provider cannot be enabled without credentials, the UI must explain this and still allow other acquisition paths such as:

```text
direct URLs
URL lists
existing dataset providers
configured discovery plugins
manual search query import
```

---

# 12. Prompt Planner

Create a planner abstraction.

Conceptually:

```text
PromptPlannerProvider
```

The planner's job is to convert a user's natural-language goal into an `AcquisitionSpec` and optionally generate initial query suggestions.

The planner must not download anything.

Required planner implementations:

## 12.1 Manual/Structured Planner

Always available.

No AI dependency.

The user fills structured fields.

## 12.2 Rule-Based Planner

Always available.

Use deterministic parsing/templates where practical.

Example:

```text
Topic: marine life
Modality: images
Target: 500
```

may deterministically generate baseline queries such as:

```text
marine life
marine animals
underwater marine life
ocean wildlife
```

Do not pretend rule-generated content is AI-generated.

## 12.3 Optional AI Planner

Support a provider interface for:

```text
small local LLM
larger local LLM
approved remote LLM
plugin
```

Do not force one model/vendor into the core.

The AI planner should produce structured output validated by Pydantic/schema validation.

Invalid model output must never directly execute.

---

# 13. Capability Resolver

Introduce an application service such as:

```text
CapabilityResolver
```

Its job is to determine which strategies can be used.

Inputs may include:

```text
hardware profile
installed models
installed plugins
available Connections
project data policy
network permissions
privacy policy
user preferences
cost limits
```

The goal remains stable.

Only the execution strategy changes.

Examples:

```text
Prompt planning:

Local LLM available
→ local LLM

No suitable local LLM, approved remote provider configured
→ remote LLM

No AI available/allowed
→ rule-based/manual planner
```

And:

```text
Image relevance:

GPU model available
→ accelerated local evaluator

No GPU
→ lightweight CPU evaluator

No model installed
→ metadata/rule evaluator + optional human review
```

Do not block the entire acquisition workflow merely because the preferred strategy is unavailable.

---

# 14. User-Selectable Strategy

Where useful, expose choices such as:

```text
Auto
Prefer Local
Local Only
Remote Allowed
Manual
Custom
```

`Auto` should be the normal simple default.

Project policy remains authoritative.

Never silently send project data to a remote AI service because local hardware is insufficient.

---

# 15. Image Acquisition Pipeline

Implement this image-first pipeline:

```text
Discover
    ↓
Preflight candidate metadata
    ↓
Shortlist
    ↓
Download
    ↓
MIME / file verification
    ↓
Image decode / corruption validation
    ↓
SHA-256
    ↓
Exact deduplication
    ↓
Resolution validation
    ↓
Basic quality
    ↓
Perceptual hash
    ↓
Near-duplicate evaluation
    ↓
OCR/text-heavy evaluation where enabled
    ↓
Relevance evaluation where enabled
    ↓
Coverage/diversity evaluation
    ↓
ACCEPT / REJECT / REVIEW
```

Order cheap operations before expensive operations.

Do not run expensive AI/model inference on candidates already known to be corrupt, exact duplicates, or below required resolution.

---

# 16. Deterministic Validation

The base workflow must function without AI.

Use existing or appropriate libraries for:

```text
file verification
MIME validation
Pillow/OpenCV decode
width/height
format
SHA-256
pHash/dHash where appropriate
basic blur/quality
OCR if installed/configured
```

Example:

```text
Target: 500 images

Downloaded: 675

Rejected:
61 exact/near duplicates
39 low resolution
8 corrupt
17 download failures
25 quality failures

Accepted:
525
```

This is a valid successful non-AI workflow.

---

# 17. RelevanceEvaluator

Quality and relevance are different.

A technically valid image may still be irrelevant to the requested topic.

Define:

```text
RelevanceEvaluator
```

Conceptually:

```python
class RelevanceEvaluator(Protocol):
    async def evaluate(
        self,
        input: RelevanceInput,
    ) -> RelevanceResult:
        ...
```

Possible implementations:

```text
metadata/keyword rules
lightweight image-text embedding model
larger local embedding model
vision-language model
approved remote model
plugin
human review
```

The core must not depend on a single model.

Model-derived results must preserve:

```text
provider
model
revision/version
parameters
input hash
timestamp
```

Use existing Feature concepts where appropriate rather than inventing duplicate feature storage.

---

# 18. Cheap-to-Expensive Evaluation Strategy

Default evaluation should generally follow:

```text
deterministic checks
        ↓
metadata relevance
        ↓
lightweight semantic evaluator if available
        ↓
high confidence?
   ┌────┴────┐
  yes        no
   │          │
decision   optional stronger evaluator
              ↓
          still uncertain?
              ↓
          human review
```

Do not send every candidate to an expensive VLM by default.

---

# 19. Human Review Is a First-Class Strategy

Support:

```text
ACCEPT
REJECT
NEEDS REVIEW
```

An uncertain candidate may enter a review queue.

Human decisions must be persisted.

Example:

```text
Automatically accepted: 438
Automatically rejected: 177
Needs review: 42
```

Human review is not failure.

It is a valid execution path.

---

# 20. TargetYieldController

Implement a real:

```text
TargetYieldController
```

This component owns the meaning of:

```text
500 usable images
```

Track at minimum:

```text
target
discovered
shortlisted
downloaded
evaluated
accepted
rejected
failed
remaining
observed acceptance rate
```

Example:

```text
Target accepted:      500
Downloaded:           300
Evaluated:            292
Accepted:             198
Rejected:              94
Failed:                 8

Observed yield:
198 / 292 = 67.8%

Remaining target:
302
```

Estimate additional candidates using observed yield.

Conceptually:

```text
remaining / estimated_yield
```

Apply conservative safety margins.

Do not use a hard-coded multiplier such as:

```text
requested * 1.3
```

as the sole strategy.

---

# 21. Batch-Based Acquisition

Do not acquire the maximum candidate budget immediately.

Use batches.

Example:

```text
Target: 500

Batch 1
150 acquired
102 accepted

Batch 2
180 acquired
124 accepted

Accepted total
226

Batch 3
220 acquired
161 accepted

Accepted total
387

Batch 4
estimated replenishment

Stop when target is satisfied.
```

Batch size may adapt based on:

```text
remaining target
acceptance rate
provider limits
network conditions
storage pressure
user budget
```

---

# 22. Query Performance Feedback

Track useful per-query/per-provider yield.

Example:

```text
Query                               Accepted / Evaluated

marine life                               42%
underwater marine wildlife                74%
coral reef wildlife photography           83%
ocean animals                             39%
```

The run may reallocate discovery effort toward productive queries.

This adaptation may be deterministic.

It does not require an LLM.

An optional planner may also propose refined queries.

Persist enough information to explain:

```text
Why did this query receive more requests?
Why was another query deprioritized?
```

---

# 23. Query Generation

Support multiple query-generation strategies.

## Deterministic

Given:

```text
marine life
```

produce useful variations through templates/taxonomy where practical.

## Manual

User provides search terms directly.

## AI-assisted

An optional planner may expand:

```text
marine life
```

into:

```text
shark underwater wildlife photography
whale underwater photography
sea turtle ocean wildlife
coral reef marine animals
octopus underwater photography
jellyfish ocean photography
```

The generated queries must be visible/editable.

---

# 24. Coverage and Diversity

A target of 500 marine-life images should not accidentally mean:

```text
470 fish
20 sharks
10 turtles
```

Support optional coverage constraints.

Example:

```yaml
coverage:
  categories:
    sharks:
      min: 50
    whales:
      min: 50
    dolphins:
      min: 50
    sea_turtles:
      min: 50
```

Also support a simpler mode such as:

```text
Balanced coverage
```

Where semantic/category evaluators are unavailable, do not fake certainty.

Offer:

```text
metadata-only approximation
manual labeling/review
disable category balancing
```

---

# 25. Source Diversity

Support optional constraints such as:

```yaml
source_diversity:
  max_fraction_per_domain: 0.30
```

Track:

```text
provider
source URL
landing page
author where available
license where available
retrieval timestamp
```

Do not make legal conclusions about licensing.

Expose provenance so the user can make informed decisions.

---

# 26. Acquisition Budget

Autonomous/replenishing acquisition must have hard safety ceilings.

Implement an `AcquisitionBudget` or equivalent configuration.

Possible limits:

```text
maximum candidates
maximum downloaded bytes
maximum final storage
maximum temporary storage
maximum requests
maximum external API cost where measurable
```

Example:

```yaml
limits:
  max_candidates: 1500
  max_download_gb: 25
  max_storage_gb: 20
  max_api_cost_usd: 5
```

If a target cannot be reached within limits:

```text
Requested accepted: 500
Accepted: 463

Stopped:
Maximum candidate limit reached.
```

Offer:

```text
Increase limit
Relax requirements
Change providers
Change queries
Accept current result
```

Never silently relax user constraints.

---

# 27. Dry Run / Acquisition Test

Before a large run, support:

```text
Test Acquisition
```

Example:

```text
Acquire/evaluate 20 candidates
        ↓
Accepted: 14
Rejected: 6

Observed yield: 70%

Estimated candidates required for 500:
~715
```

Dry-run information should include where practical:

```text
candidate estimate
download estimate
storage estimate
expected expensive model operations
enabled providers
remote services
possible external costs
```

---

# 28. Responsible Internet Acquisition

All remote discovery/acquisition must follow the existing MediaSensei web principles.

Use:

```text
connection pooling
async downloads
per-domain concurrency
adaptive throttling
retry/backoff
Retry-After
caching
duplicate URL prevention
checksums
resumability
```

Do not implement:

```text
CAPTCHA defeat
access-control bypass
authentication bypass
dataset gate bypass
stealth blocking circumvention
```

If user interaction is required:

```text
Source paused.

Interaction required.

[Retry]
[Skip]
[Open Provider]
[Use Alternative Source]
```

---

# 29. Project Policy

Remote acquisition and remote processing are not the same permission.

Extend policy semantics if necessary to distinguish:

```text
Remote Acquisition
Remote Processing
```

Examples:

```text
Remote Acquisition:
Disabled
Approved Providers
Allowed

Remote Processing:
Disabled
Approved Providers
Allowed
```

A project may reasonably allow:

```text
download public media from approved providers
```

while forbidding:

```text
send project assets to a cloud AI model
```

Do not silently conflate the two.

---

# 30. Persistent Jobs

Do not perform long acquisition inside a FastAPI request.

Use the existing persistent job/worker architecture.

Suggested run hierarchy:

```text
AcquisitionRun
│
├── PlanningJob
├── DiscoveryJobs
├── DownloadJobs
├── ValidationJobs
├── RelevanceJobs
└── ReplenishmentJobs
```

The actual representation may differ if the existing job/pipeline engine has a cleaner pattern.

Use existing infrastructure rather than creating a second job system.

---

# 31. Restart and Resume

If the application stops after:

```text
430 / 500 accepted
```

restarting must recover approximately from:

```text
430 / 500
```

Do not start discovery/download from zero.

Persist:

```text
run state
queries
provider cursors where possible
candidate states
download attempts
accepted/rejected decisions
budgets consumed
yield estimates
```

Completed candidate work should not be repeated unnecessarily.

---

# 32. Candidate Idempotency

Prevent duplicate work.

Use stable identifiers where available:

```text
provider + remote ID
canonicalized source URL
content hash after download
```

The same candidate discovered from multiple queries should not automatically cause multiple downloads.

The same physical content acquired from multiple sources should deduplicate through the existing content-addressed object store while retaining source/provenance relationships where appropriate.

---

# 33. Multimodal TargetSpec

Do not hard-code:

```text
target = file_count
```

Define a reusable `TargetSpec`.

Examples:

## Images

```yaml
unit: accepted_assets
count: 500
```

## Video

```yaml
unit: clips
count: 100
```

or:

```yaml
unit: total_duration_seconds
count: 36000
```

## Audio

```yaml
unit: total_duration_seconds
count: 180000
```

## Documents

```yaml
unit: documents
count: 10000
```

or eventually:

```yaml
unit: tokens
count: 100000000
```

## Tabular

```yaml
unit: rows
count: 1000000
```

Only image target fulfillment is required to be fully proven end-to-end in this milestone.

---

# 34. Modality Evaluator Contracts

Architect evaluators by modality.

Conceptually:

```text
ImageCandidateEvaluator
VideoCandidateEvaluator
AudioCandidateEvaluator
DocumentCandidateEvaluator
TabularCandidateEvaluator
```

The image evaluator is required now.

Other evaluator contracts may be light/provisional until their intelligent acquisition workflows are implemented.

Do not build giant universal conditionals such as:

```python
if image:
    ...
elif video:
    ...
elif audio:
    ...
```

inside one unmaintainable module.

---

# 35. Image Evaluator

Image evaluation may combine:

```text
decode/integrity
dimensions
format
SHA-256
pHash/dHash
basic blur/quality
OCR/text coverage
metadata relevance
optional semantic relevance
coverage classification
```

Every expensive or model-based result should integrate with the existing Feature/provenance model where appropriate.

---

# 36. Video/Audio/Document Readiness

Ensure the architecture can later use:

## Video

```text
provider discovery
yt-dlp/direct/provider acquisition
ffprobe
FFmpeg
frame sampling
visual relevance
duration-based TargetSpec
```

## Audio

```text
provider discovery
direct/provider acquisition
FFmpeg
duration
sample rate
channels
silence
audio relevance
duration-based TargetSpec
```

## Documents

```text
web/document discovery
HTTP/provider acquisition
document parser
content hashing
duplicate text detection
language
semantic relevance
document/token target
```

Do not require full implementation of these semantic layers now.

---

# 37. UI — Acquire Data

Add a clear project action such as:

```text
Acquire Data
```

Initial UX:

```text
What do you want to acquire?

[ 500 real marine-life images, at least 768px... ]

[Build Plan]
```

Do not require the user to write a prompt.

Also provide:

```text
[Configure Manually]
```

---

# 38. UI — Manual Acquisition Builder

Example fields:

```text
Modality
[ Images ▼ ]

Topic
[ Marine life ]

Target accepted
[ 500 ]

Minimum width
[ 768 ]

Minimum height
[ 768 ]

Reject corrupt             ✓
Reject exact duplicates    ✓
Reject near duplicates     ✓
Reject text-heavy          ✓

Relevance
[ Auto ▼ ]

Sources
[ Configure ]

Limits
[ Advanced ]

[Build Acquisition Plan]
```

AI may populate these fields.

The user owns the configuration.

---

# 39. UI — Plan Review

Before a large run show:

```text
Acquisition Plan

Target
500 accepted images

Estimated candidates
650–850

Queries
12

Providers
3 enabled

Minimum resolution
768 × 768

Exact duplicate filtering
Enabled

Near-duplicate filtering
Enabled

Relevance strategy
Lightweight local

Maximum candidates
1,500

Estimated download
2.4–4.1 GB
```

Actions:

```text
Edit
Test with 20
Start Acquisition
```

---

# 40. UI — Progress

Example:

```text
Marine Life Acquisition

████████████████░░░░ 412 / 500 accepted

Discovered        823
Downloaded        641
Evaluated         619
Accepted          412
Rejected          185
Failed             22

Observed yield    66.6%

Estimated additional candidates
~140
```

Show useful current activity:

```text
Current query
Current provider
Current batch
Coverage shortages where available
```

Provide:

```text
Pause
Resume
Cancel
View Rejections
View Sources
View Logs
```

---

# 41. UI — Rejection Inspection

Allow users to inspect rejected candidates by reason.

Example:

```text
Exact duplicates       31
Near duplicates        54
Low resolution         39
Corrupt                 7
Irrelevant             61
Text-heavy             22
Low quality            18
```

Do not permanently delete raw acquired objects through ordinary rejection actions if they have already entered the immutable object store.

Use logical exclusion/quarantine according to existing MediaSensei data-safety rules.

---

# 42. REST API

Add versioned endpoints consistent with `/api/v1/`.

Suggested resource groups:

```text
/acquisition/requests
/acquisition/specs
/acquisition/plans
/acquisition/runs
/acquisition/candidates
/acquisition/providers
```

Exact paths may be adjusted to match current API conventions.

Required operations should cover:

```text
create request/spec
build plan
test plan
start run
get run
pause/resume/cancel where supported
list candidates
list decisions/rejections
inspect providers/capabilities
```

Use existing structured error patterns.

Do not expose provider secrets.

---

# 43. Python SDK

Provide a straightforward workflow.

Conceptually:

```python
project = Project.open(...)

spec = project.acquisition.create_spec(
    modality="image",
    topic="marine life",
    target=500,
)

plan = spec.plan()

run = plan.start()
```

And prompt convenience where a planner exists:

```python
plan = project.acquisition.from_prompt(
    "Get 500 real marine-life images, minimum 768px."
)
```

The prompt method must not be the only API.

---

# 44. CLI

Provide a useful subset.

Examples:

```bash
mediasensei acquire plan \
  --modality image \
  --topic "marine life" \
  --target 500

mediasensei acquire test PLAN_ID --count 20

mediasensei acquire run PLAN_ID

mediasensei acquire status RUN_ID

mediasensei acquire candidates RUN_ID
```

Prompt convenience may be added:

```bash
mediasensei acquire prompt \
  "Get 500 marine-life images, at least 768px"
```

Do not expose every advanced GUI field as a CLI flag if it harms usability.

Structured YAML/JSON config may be supported for advanced use.

---

# 45. Provenance

Every acquisition run should preserve enough information to answer:

> Where did this come from, and why did MediaSensei acquire/accept it?

Record where applicable:

```text
original prompt
normalized AcquisitionSpec
planner provider/model/version
generated queries
manual query edits
discovery providers
provider/plugin versions
candidate source URL
landing page
retrieval timestamp
download attempt
content hash
validation results
quality findings
relevance provider/model/version
accept/reject/review decision
human override
budget configuration
run version
```

Do not store credentials in provenance exports.

---

# 46. Reproducibility

Prompt-based behavior must still be reproducible enough to inspect and re-run.

External search results may change over time.

Do not falsely promise bit-for-bit reproducibility of live internet search.

Instead preserve:

```text
spec
queries
provider
provider parameters
timestamps
candidate identifiers/URLs
download hashes
versions
decisions
```

This provides reproducibility of the process and traceability of the resulting dataset even when the live internet changes.

---

# 47. Observability

Track:

```text
discovery requests
provider latency
provider errors
download throughput
download failures
bytes downloaded
candidate counts
accept/reject counts
rejection reasons
acceptance rate
query yield
provider yield
cache hits
duplicate hits
retries
replenishment cycles
```

A user should be able to understand:

```text
Why is acquisition slow?
Why are many files being rejected?
Why is MediaSensei downloading more than the target count?
Why did it stop before reaching the target?
```

---

# 48. Security

Minimum requirements:

- validate URLs;
- protect against path traversal;
- safe filename handling;
- safe archive handling where applicable;
- configurable download size limits;
- content type verification;
- no secret logging;
- restrictive remote-provider permissions;
- SSRF-aware handling for server-side URL fetches;
- safe redirect handling;
- deny/limit dangerous local/private network targets where appropriate;
- provider credentials through existing credential vault/connections;
- no unrestricted arbitrary command execution through discovery adapters.

---

# 49. Dependency Policy

Keep base installation reasonable.

Do not install:

```text
large LLM frameworks
large vision-language models
multiple OCR stacks
multiple embedding stacks
every downloader/provider SDK
```

simply to enable this milestone.

Prefer:

```text
small core dependencies
optional extras
provider adapters
on-demand models
plugins
```

The no-AI deterministic image workflow must remain available with a reasonable installation footprint.

---

# 50. Testing Strategy

Create deterministic tests that do not depend on the live public internet for correctness.

Required:

## Unit tests

Cover:

```text
AcquisitionSpec validation
TargetSpec
candidate state transitions
decision reason codes
yield calculations
batch sizing
budget enforcement
query/provider statistics
capability resolution
policy blocking
URL/candidate deduplication
```

## Integration tests

Use:

```text
mock discovery provider
local HTTP fixture server
small image fixtures
duplicate fixtures
corrupt fixtures
low-resolution fixtures
text-heavy fixtures where practical
```

Prove the complete acquisition loop.

## Optional live-provider tests

If implemented, mark live external tests separately.

They must not be required for normal deterministic CI.

---

# 51. Target Yield Tests

Create explicit tests such as:

```text
Target: 10 accepted

Provider supplies:
3 corrupt
2 duplicates
1 low-resolution
10 acceptable
```

Expected behavior:

```text
MediaSensei keeps requesting candidates
until 10 accepted assets exist
or a configured limit is reached.
```

Also test:

```text
target cannot be reached before max_candidates
→ completed_with_shortfall
```

---

# 52. Restart-Safety Tests

Test:

```text
Run target: 20

10 accepted
worker stops
worker restarts
```

Expected:

```text
completed candidates remain completed
accepted count remains 10
run resumes
target eventually reaches 20
```

Do not redownload/reprocess completed work unnecessarily.

---

# 53. No-AI Acceptance Test

This is mandatory.

Disable:

```text
LLM planner
remote AI
GPU semantic model
VLM
```

Then prove:

```text
manual/rule-based image acquisition
→ discovery
→ download
→ validation
→ dedup
→ quality
→ target yield
→ completion
```

The feature must remain useful.

---

# 54. Optional-AI Acceptance Test

Where a lightweight optional planner/evaluator is available, prove that:

```text
natural language
→ validated AcquisitionSpec
```

and/or:

```text
candidate
→ semantic relevance result
```

Do not make CI depend on downloading a huge model.

Use mocks or tiny test adapters where appropriate.

---

# 55. End-to-End Acceptance Scenario

The following scenario must work.

A user creates or opens a Project.

They select:

```text
Acquire Data
```

They enter:

```text
Get me 500 usable images of marine life.

Prefer real photographs.

Include a reasonable variety of:
sharks, whales, dolphins, turtles,
coral reefs, octopus, jellyfish and tropical fish.

Minimum resolution: 768×768.

Avoid corrupt files, duplicates and text-heavy images.
```

MediaSensei:

1. preserves the original request;
2. creates a validated `AcquisitionSpec`;
3. shows the structured plan;
4. allows the user to edit it;
5. shows selected discovery providers;
6. shows configured safety/budget limits;
7. optionally tests a small sample;
8. starts a persistent AcquisitionRun;
9. discovers candidate images;
10. avoids obvious duplicate candidate URLs;
11. downloads candidates incrementally;
12. validates image integrity;
13. verifies MIME/type;
14. computes SHA-256;
15. performs exact deduplication;
16. checks minimum resolution;
17. performs basic quality checks;
18. computes perceptual hash where configured;
19. detects/rejects near-duplicates where configured;
20. runs OCR/text-heavy evaluation where configured and available;
21. evaluates relevance using the selected available strategy;
22. accepts/rejects/reviews candidates with explicit reasons;
23. tracks accepted count;
24. calculates observed usable yield;
25. requests additional batches when needed;
26. adapts batch size based on observed yield;
27. respects provider limits and project policy;
28. stops when at least 500 accepted assets exist or a safety limit is reached;
29. catalogs accepted assets into the Project;
30. preserves source/provenance;
31. preserves run history and rejection reasons;
32. survives worker/application restart;
33. allows accepted assets to feed the existing Dataset workflow.

Example result:

```text
Acquisition completed

Requested accepted images      500
Accepted                       500

Candidates discovered         1042
Downloaded                     732
Evaluated                      710

Rejected:
  exact duplicates              31
  near duplicates               54
  low resolution                39
  corrupt                        7
  irrelevant                    61
  text-heavy                    22
  low quality                   18

Failed downloads                22

Sources                          4
Queries                         23
Replenishment cycles             4
```

The exact numbers do not matter.

The behavior does.

---

# 56. Shortfall Acceptance Scenario

If the user requests:

```text
500 accepted
```

but safety limits are reached at:

```text
463 accepted
```

MediaSensei must report:

```text
Completed with shortfall

Requested: 500
Accepted: 463

Reason:
Maximum candidate budget reached.
```

Actions may include:

```text
Increase Budget
Relax Requirements
Change Sources
Change Queries
Accept Current Result
```

Do not silently return 463 as if 500 were achieved.

---

# 57. Capability Graceful-Degradation Acceptance Scenario

Test at least these conceptual environments:

## Environment A

```text
GPU available
local semantic model installed
```

Expected:

```text
use accelerated local relevance where selected
```

## Environment B

```text
CPU only
no large model
```

Expected:

```text
use deterministic checks
+
lightweight available evaluator or metadata rules
```

## Environment C

```text
no AI models
remote AI disabled
```

Expected:

```text
manual/rule-based planning
+
deterministic acquisition
+
optional human review
```

All three environments must be able to use Intelligent Acquisition.

They may differ in automation, speed, and precision.

They must not become three different products.

---

# 58. Architecture Decision Records

Create/update ADRs for significant decisions.

Likely ADRs include:

```text
Intelligent Acquisition lifecycle
Discovery vs Acquisition separation
AcquisitionSpec as execution source of truth
Target yield / adaptive replenishment
Capability resolution and graceful degradation
Remote acquisition vs remote processing policy
Relevance evaluator abstraction
```

Use the repository's existing ADR numbering.

---

# 59. Documentation

Add/update:

```text
Architecture overview
Intelligent Acquisition architecture
User guide: Acquire Data
Prompt-based acquisition
Manual acquisition
Discovery provider development
Relevance evaluator development
Project policy implications
CLI quickstart
Python SDK quickstart
Troubleshooting
```

Include examples with AI disabled.

Do not document AI as mandatory.

---

# 60. Plugin Contract Implications

This milestone should produce real usage evidence for later Plugin SDK finalization.

Document exactly which contracts the next plugin milestone should stabilize.

Potential public capabilities:

```text
DiscoveryProvider
SourceConnector
PromptPlannerProvider
RelevanceEvaluator
```

Do not prematurely declare every provisional interface permanently stable.

At the end of this milestone, create a short plugin-contract report covering:

```text
contracts exercised
official implementations
configuration schemas
error semantics
streaming/pagination behavior
credential requirements
capability metadata
compatibility concerns
```

The subsequent Plugin SDK milestone should use this report.

---

# 61. Implementation Order Inside This Milestone

Do not implement everything simultaneously.

Use internal gates.

## Gate A — Domain/Application Foundation

Implement:

```text
AcquisitionRequest
AcquisitionSpec
TargetSpec
AcquisitionPlan
AcquisitionRun
AcquisitionQuery
AcquisitionCandidate
AcquisitionDecision
budgets
state transitions
persistence
```

Acceptance:

```text
migrations pass
restart-safe models
unit tests pass
```

---

## Gate B — Discovery

Implement:

```text
DiscoveryProvider contract
mock provider
one practical image discovery provider
pagination/cursors where applicable
candidate persistence
URL/provider deduplication
```

Acceptance:

```text
search returns persisted candidates
provider errors do not corrupt runs
tests pass
```

---

## Gate C — Deterministic Image Acquisition

Implement:

```text
candidate acquisition
download limits
integrity validation
SHA-256
exact dedup
resolution
basic quality
pHash/near-duplicate checks
```

Acceptance:

```text
complete no-AI image flow works
```

---

## Gate D — Target Yield

Implement:

```text
batch acquisition
yield measurement
replenishment
budgets
shortfall
```

Acceptance:

```text
target accepted count is satisfied when possible
```

---

## Gate E — Capability Resolution

Implement:

```text
manual planner
rule planner
capability resolver
project policy integration
```

Acceptance:

```text
feature remains useful without AI
```

---

## Gate F — Optional Intelligence

Implement, without destabilizing prior gates:

```text
optional AI planner adapter
optional relevance evaluator adapter
uncertain/review path
```

Acceptance:

```text
AI can improve planning/relevance
AI remains optional
```

---

## Gate G — Interfaces

Complete:

```text
React UI
REST
CLI
SDK
progress
review/rejection inspection
```

Acceptance:

```text
same core/application services power all interfaces
```

---

## Gate H — Reliability / Documentation

Complete:

```text
restart tests
provider failure tests
budget tests
docs
ADRs
plugin-contract report
```

Only then mark the milestone complete.

---

# 62. Definition of Done

This milestone is complete only when:

1. migrations work;
2. backend starts;
3. frontend builds;
4. lint passes;
5. type checking passes;
6. unit tests pass;
7. integration tests pass;
8. no-AI acquisition works end-to-end;
9. target-yield replenishment works;
10. shortfall behavior is explicit;
11. provider failures are recoverable;
12. acquisition jobs survive restart;
13. accepted assets preserve provenance;
14. raw data safety remains intact;
15. project policy is enforced;
16. AI remains optional;
17. UI exposes prompt and manual workflows;
18. API/CLI/SDK use the same application core;
19. documentation is updated;
20. ADRs are updated;
21. plugin-facing contract implications are documented;
22. existing Dataset Provider workflows still pass;
23. existing image/dataset workflows are not regressed.

Do not proceed to Plugin SDK finalization/hardening while this milestone has failing foundations.

---

# 63. Required Final Report

At milestone completion, provide:

```text
implementation summary
files/modules added
migrations added
architecture decisions
discovery providers implemented
acquisition mechanisms implemented
no-AI workflow status
optional AI workflow status
relevance strategies implemented
tests added
test results
known limitations
plugin contracts discovered/refined
follow-up items for Plugin SDK milestone
```

Also explicitly report:

```text
Can Intelligent Acquisition run with no LLM?
Can it run with no GPU?
Can it resume after restart?
Can it reach a target accepted count adaptively?
Can users inspect why candidates were rejected?
Can providers be replaced without changing domain core?
```

---

# 64. Final Product Standard

Do not build a demo scraper.

Build the foundation of a serious acquisition subsystem.

A basic machine should still be capable of:

```text
discover
download
validate
deduplicate
filter
review
catalog
```

Better hardware or configured AI may add:

```text
natural-language planning
better query expansion
semantic relevance
automatic coverage management
less human review
```

The user's goal remains the same.

Only the path changes.

Remember:

> **AI-enhanced, not AI-dependent.**

> **Do not turn missing capability into a dead end. Turn it into another path.**

And:

> **Use software where software is enough. Use AI where AI makes the result better. Never require AI merely because AI is available.**
