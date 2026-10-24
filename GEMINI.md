# GEMINI.md
# Project Master Instructions

## 1. Project Overview

**Project Title:** Integrated AI Surveillance and FIR Assistance System

This is a final-year Computer Science and Engineering project intended to assist citizens and police personnel through AI-assisted complaint processing, missing-person identification, and First Information Report (FIR) drafting.

The complete project is planned to contain multiple modules. However, the current implementation must focus exclusively on the FIR Assistance Module.

The system is a student-developed prototype. It must not claim to be an official police system or represent generated documents as legally registered FIRs.

## 2. Primary Objective

Build a working web application that allows a citizen to submit a complaint in English, Malayalam, or Hindi and assists in converting the submitted information into a structured Malayalam FIR draft.

The application must also provide a separate police review interface where an authorized reviewer can inspect, edit, and update the status of the generated draft.

The system must prioritize factual accuracy, transparency, privacy, usability, and a clear distinction between AI-generated content and human-reviewed content.

## 3. Current Scope and Future Scope

### 3.1 Current Implementation Scope

Implement only the following features:

1. Citizen complaint submission.
2. Input validation.
3. Complaint category selection and basic complaint processing.
4. Identification of missing or ambiguous information.
5. AI-assisted generation of a Malayalam FIR draft.
6. Display and editing of the generated draft.
7. Police review and editing interface.
8. Draft review status management.
9. Basic error handling and testing.

### 3.2 Future Scope — Do Not Implement Yet

The following features are planned for later development:

- Missing-person face detection and recognition.
- Processing CCTV video footage.
- Matching detected faces against a missing-person database.
- Notifications to police stations.
- Citizen accounts and authentication.
- Case tracking and communication.
- Full administrator dashboard.
- Production deployment and integration with real police systems.

Do not implement these future features unless explicitly instructed.

## 4. Technology Stack

Use the following technologies for the initial implementation.

### 4.1 Programming Language

**Python**

Use Python for the application logic, input processing, model integration, and related functionality.

### 4.2 Web Application Framework

**Streamlit**

Use Streamlit to create the initial web interface, including forms, text areas, buttons, navigation, and review screens.

Avoid introducing a separate frontend framework unless explicitly requested.

### 4.3 Language Model

Initially, implement and test the application using a clearly labelled mock FIR draft generator.

After the basic application works, integrate an existing language model through an API or another explicitly approved inference method.

The final model has not yet been selected. Possible candidates include suitable Qwen models and other models that demonstrate adequate Malayalam language performance.

Do not assume that a particular model is best without testing it.

Do not train a model during the initial application-building stages.

### 4.4 Future Fine-Tuning

The project may later experiment with supervised fine-tuning using LoRA or QLoRA.

Any fine-tuning must be treated as a separate stage involving dataset preparation, training, evaluation, and comparison against the original model.

Do not begin fine-tuning until the basic application works and the model choice, dataset, and available computing resources have been assessed.

### 4.5 Dependencies

Use only the dependencies required for the current stage.

Maintain a `requirements.txt` file with the necessary Python packages and appropriate version constraints where practical.

Do not install unrelated packages or introduce unnecessary architectural complexity.

## 5. Functional Requirements

### 5.1 Citizen Complaint Form

Create a clean form that collects the following information:

- Complainant name.
- Contact number.
- Complaint category.
- Incident date.
- Incident location.
- Complaint description.
- Optional additional information relevant to the incident.

The complaint description must accept Unicode text, including Malayalam characters.

The interface must support complaints written in English, Malayalam, or Hindi.

Do not require users to enter information that is genuinely unknown. Missing information must be identified and handled explicitly.

### 5.2 Input Validation

Validate the submitted form before processing it.

Requirements:

- Check required fields.
- Reject empty or whitespace-only required values.
- Validate date input.
- Apply reasonable contact-number validation without assuming that all valid numbers follow one exact format.
- Display clear error messages near the relevant fields or in an accessible error area.
- Preserve the user's entered information when validation fails.
- Never silently replace invalid input with invented values.

### 5.3 Complaint Processing

Process the submitted complaint to identify relevant information.

Where supported, identify:

- Complaint category.
- Incident date and time.
- Incident location.
- Persons involved.
- Relevant objects or property.
- Description of the incident.
- Details that are missing, ambiguous, or contradictory.

Do not infer guilt or present allegations as established facts.

Do not invent names, addresses, dates, witness statements, evidence, motives, or legal conclusions.

If an important detail is missing, generate a list of follow-up questions rather than guessing.

### 5.4 FIR Draft Generation

The system must help produce a structured Malayalam FIR draft using the information supplied by the complainant and any explicitly confirmed follow-up answers.

The generated draft must:

- Preserve the meaning of the original complaint.
- Use clear and formal Malayalam.
- Maintain factual consistency.
- Avoid unsupported statements.
- Clearly identify missing information where necessary.
- Avoid inventing applicable laws, legal sections, evidence, or police actions.
- Remain editable after generation.

The output must be labelled:

**"AI-Generated FIR Draft — Pending Human Review"**

Do not represent this generated document as an officially registered FIR.

### 5.5 Draft Display and Editing

Display the generated draft in an editable text area.

The user or authorized reviewer must be able to inspect the draft before it is considered ready for review.

Where practical, show the original complaint and generated draft separately so that the supplied facts can be compared against the generated content.

If generation fails, display a useful error message and allow the user to retry.

Do not discard the original complaint because generation failed.

### 5.6 Police Review Interface

Create a separate section or page for police review.

The interface must display:

- Complaint information.
- Original complaint description.
- Generated Malayalam FIR draft.
- Editable draft text.
- Current review status.
- A field for reviewer comments, where appropriate.

Support the following demonstration statuses:

1. **Pending Review** — the draft has not yet been reviewed.
2. **Approved** — the draft has been marked approved within the demonstration workflow.
3. **Returned for Correction** — the draft requires changes.

Allow the reviewer to edit the draft and update its status.

An approval status in this prototype must not be described as legal registration or official filing.

Do not claim that the application has verified the identity or authority of a police officer unless authentication is actually implemented.

### 5.7 Demonstration Data

Use fictional data for development and demonstrations.

Clearly label demonstration records as sample data.

Do not include real personal information, real police case details, or confidential records in test fixtures, example prompts, screenshots, or public repositories.

## 6. AI Integration Rules

When integrating an actual language model:

1. Keep the model integration separate from the user interface.
2. Store API keys in environment variables or an appropriate local secrets mechanism.
3. Never hardcode API keys in source files.
4. Never commit `.env` files or other secrets to GitHub.
5. Provide a `.env.example` file containing placeholder values only, if needed.
6. Handle API errors, timeouts, rate limits, and unavailable services gracefully.
7. Do not expose internal prompts, credentials, or sensitive data unnecessarily.
8. Do not silently fall back to mock output while presenting it as real AI output.
9. Clearly indicate whether a result was generated by a mock implementation or an actual model.
10. Make it possible to change the model without rewriting the entire application.

The application must not require a paid service to run its initial mock demonstration.

## 7. Hallucination Prevention and Factual Validation

Fine-tuning alone does not guarantee that hallucinations will be eliminated.

Use several safeguards:

- Instruct the model to use only supplied and confirmed facts.
- Keep original complaint data available for comparison.
- Identify missing information explicitly.
- Ask follow-up questions when required.
- Validate structured model output before using it.
- Check that critical facts in the generated draft are supported by the complaint.
- Avoid presenting unverified model-generated legal sections as authoritative.
- Preserve human review as a required stage before approval.

If the model cannot determine a detail, it must indicate that the detail is unknown rather than inventing an answer.

## 8. Privacy and Security

Follow these requirements throughout development:

- Use fictional complaint data by default.
- Do not expose API keys or credentials.
- Avoid logging full complaint descriptions or personal details unnecessarily.
- Do not send real sensitive complaint information to an external model API without appropriate authorization, privacy review, and safeguards.
- Do not claim that the application is secure for production use without appropriate testing.
- Do not implement fake authentication that is presented as real authentication.
- Do not claim that a reviewer has a verified police identity when the prototype has no such verification.

The initial prototype is for demonstration and evaluation, not for handling actual police complaints.

## 9. Code Quality and Architecture

Write code that a beginner CSE student can understand and explain.

Requirements:

- Use meaningful variable and function names.
- Add comments to explain important or non-obvious logic.
- Keep functions reasonably small and focused.
- Separate UI code, complaint-processing logic, and model integration where appropriate.
- Avoid unnecessary abstraction and complicated design patterns.
- Handle exceptions explicitly.
- Avoid duplicated logic.
- Use clear file and folder names.
- Do not introduce databases or additional services unless required by the current implementation stage.

Prefer a small, working, understandable implementation over an unnecessarily complex architecture.

## 10. Testing Requirements

Test the application using fictional complaints.

At minimum, test:

1. Valid complaint submission.
2. Missing required fields.
3. Empty or whitespace-only input.
4. Malayalam complaint text.
5. Hindi complaint text.
6. English complaint text.
7. Missing incident details.
8. Editing the generated draft.
9. Changing the review status.
10. Handling generation failures.
11. Preventing unsupported facts from being introduced by the mock generator.
12. Handling API failures after real model integration.

For real model integration, evaluate factual consistency and Malayalam output quality separately from ordinary application functionality.

Do not claim that tests passed unless they were actually executed.

## 11. Implementation Plan

Implement the project in the following order.

### Stage 1 — Repository Inspection and Basic Interface

- Inspect the repository and existing README.
- Read `GEMINI.md` and `BRAND_GUIDELINES.md`.
- Preserve relevant existing information.
- Create the minimum required Streamlit application structure.
- Build the initial interface and verify that the application starts.

### Stage 2 — Complaint Form and Validation

- Implement all required complaint fields.
- Add validation.
- Ensure that Malayalam and Hindi text can be entered and preserved.
- Test valid and invalid submissions.

### Stage 3 — Mock Draft Generation

- Implement a deterministic, clearly labelled mock generator.
- Do not pretend that the mock generator is an LLM.
- Use supplied information only.
- Identify missing information.
- Generate a demonstration Malayalam draft where feasible.

### Stage 4 — Police Review Workflow

- Add draft editing.
- Add review comments where appropriate.
- Implement the three demonstration statuses.
- Ensure that edits and status changes work as expected.

### Stage 5 — Real LLM Integration

Only after the preceding stages work:

- Review candidate models and their licences.
- Assess Malayalam drafting quality.
- Select the model and inference method.
- Implement secure configuration and error handling.
- Test the model using fictional complaints.
- Clearly distinguish real model output from mock output.

### Stage 6 — Evaluation and Fine-Tuning Investigation

- Prepare a small, carefully checked dataset of fictional complaint-and-draft examples.
- Separate training examples from evaluation examples.
- Establish a baseline using the original model.
- Investigate LoRA or QLoRA if resources permit.
- Compare the original and adapted models.
- Measure factual consistency, completeness, Malayalam quality, and formatting.
- Do not claim that fine-tuning improves performance unless evaluation results support the claim.

## 12. Instructions for Antigravity

Before modifying the project:

1. Read this entire file.
2. Read `BRAND_GUIDELINES.md`.
3. Inspect the existing repository structure and relevant source files.
4. Determine which implementation stage is currently in progress.
5. Do not recreate existing files unnecessarily.
6. Do not delete or overwrite useful work without explicit permission.

During implementation:

- Follow the implementation stages in order.
- Work only on the next requested stage.
- Do not silently expand the project scope.
- Explain important implementation decisions in beginner-friendly language.
- Keep the code readable and suitable for a student to explain during a project demonstration or viva.
- Run relevant tests and report the actual results.
- Do not deploy, publish, push to GitHub, or perform destructive Git operations without explicit permission.

After each stage, report:

1. What was implemented.
2. Which files were created or modified.
3. How the implementation works.
4. How to run it on Windows.
5. Which tests were executed and their results.
6. Any remaining limitations or known issues.
7. The recommended next step.

If requirements are ambiguous, explain the ambiguity and ask before making major architectural decisions.

## 13. Final Guiding Principle

Build a working, understandable, testable student prototype that demonstrates responsible AI-assisted FIR drafting.

Prioritize factual accuracy, transparent AI use, Malayalam readability, privacy, and human review over unnecessary features.

The application must never fabricate complaint details or misrepresent an AI-generated draft as an officially registered FIR.

Implement the project incrementally and verify each stage before proceeding to the next.
