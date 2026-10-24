# BRAND_GUIDELINES.md
# Brand and User Interface Design Guidelines

## 1. Design Vision

The Integrated AI Surveillance and FIR Assistance System must have a clean, professional, trustworthy, and accessible interface.

The application is intended to assist citizens in submitting complaints and help police personnel review AI-generated FIR drafts.

The design should communicate:

- Trust and reliability.
- Clarity and simplicity.
- Professionalism.
- Responsible use of AI.
- Transparency about the status of generated documents.
- Ease of use for people with different levels of technical knowledge.

The interface must look like a well-designed academic software prototype, not an imitation of an official police or government portal.

## 2. Brand Personality

The application should feel:

- Professional, not intimidating.
- Modern, but not overly decorative.
- Simple, but not unfinished.
- Trustworthy, without making unsupported security claims.
- AI-assisted, without suggesting that AI replaces human judgment.
- Suitable for both citizen-facing forms and police review workflows.

Avoid excessive animations, flashy effects, decorative illustrations, and unnecessary visual complexity.

## 3. Colour Palette

Use a restrained navy, white, and light-grey colour palette.

### 3.1 Primary Colours

**Primary Navy**
- Hex: `#17365D`
- Use for primary buttons, major headings where appropriate, selected navigation elements, and important interface accents.

**Deep Navy**
- Hex: `#10243A`
- Use sparingly for dark navigation areas or strong visual emphasis.

**White**
- Hex: `#FFFFFF`
- Use for the main page background and content surfaces where appropriate.

**Light Grey**
- Hex: `#F4F6F8`
- Use for the overall application background and subtle section separation.

### 3.2 Supporting Colours

**Secondary Blue**
- Hex: `#315B86`
- Use for links, secondary actions, and restrained highlights.

**Border Grey**
- Hex: `#D9E0E7`
- Use for input borders, card outlines, dividers, and section boundaries.

**Primary Text**
- Hex: `#1F2937`
- Use for body text and form labels.

**Secondary Text**
- Hex: `#5B6573`
- Use for helper text, descriptions, timestamps, and secondary information.

### 3.3 Status Colours

Use status colours consistently and always pair them with readable text.

- Pending Review: amber, `#B7791F`.
- Approved: green, `#237A4B`.
- Returned for Correction: red, `#B42318`.
- Informational: blue, `#315B86`.
- Error: red, `#B42318`.

Status colours must not be the only way information is communicated. Include the full status label.

Do not use large coloured backgrounds for ordinary content.

## 4. Typography

Use a simple, readable sans-serif typeface.

Preferred font stacks:

- General interface: system sans-serif.
- English headings and body text: a readable sans-serif font.
- Malayalam content: a Malayalam-compatible Unicode font, such as Noto Sans Malayalam when available.
- Hindi content: a Devanagari-compatible Unicode font, such as Noto Sans Devanagari when available.

Do not assume that every system has the same fonts installed. Use sensible fallbacks.

### Typography Hierarchy

- Page title: prominent, clear, and concise.
- Section heading: visually distinct from the body text.
- Form label: readable and placed consistently near its field.
- Body text: comfortable to read without unnecessary small text.
- Helper text: smaller but still legible.
- Status label: clear and easy to identify.
- FIR draft: readable, with appropriate line spacing and paragraph separation.

Avoid decorative typefaces and excessive font-weight variation.

Ensure that Malayalam characters render correctly without clipping or broken glyphs.

## 5. Layout and Spacing

Use a consistent spacing system throughout the application.

Preferred spacing increments:
- 4 px: very small internal spacing.
- 8 px: spacing between closely related elements.
- 12 px: compact component spacing.
- 16 px: standard spacing.
- 24 px: spacing between sections.
- 32 px: separation between major content areas.

Use a consistent alignment system for headings, forms, cards, buttons, and draft content.

Avoid overcrowded pages and excessively wide text blocks.

On desktop screens, use a readable content width and clear separation between the main form and secondary information.

On mobile screens, stack content vertically and ensure that form fields and buttons remain usable.

## 6. Navigation

Keep navigation simple and predictable.

The main application should provide clear access to:

1. Citizen Complaint Submission.
2. Police Draft Review.

The two areas must be visually distinguishable.

Do not add navigation items for features that have not been implemented.

Do not display missing-person recognition, CCTV monitoring, notifications, administrator dashboards, or case tracking as functional features until they actually exist.

Use clear navigation labels rather than unexplained icons.

## 7. Page Design

### 7.1 Application Header

The header should contain:

- The project name or a shortened application title.
- A brief description of the application's purpose.
- Simple navigation where appropriate.

Use a clean layout with restrained navy accents.

Do not include official police insignia, government seals, official department logos, or any other elements that imply government affiliation.

### 7.2 Citizen Complaint Page

The complaint submission page should feel simple and approachable.

Organize fields in a logical sequence:

1. Complainant information.
2. Incident information.
3. Complaint description.
4. Review and submission action.

Use clearly visible labels and appropriate input types.

Group related fields into sections without creating too many separate cards.

For complaint descriptions, provide a sufficiently large text area.

Use helper text to explain what information should be entered.

Allow citizens to enter Malayalam, Hindi, or English text.

Avoid relying exclusively on placeholders as field labels.

### 7.3 Complaint Processing Feedback

When the application processes a complaint, display clear feedback about the current action.

Examples include:

- Processing complaint.
- Identifying missing information.
- Preparing Malayalam draft.
- Draft generation failed; please try again.

Do not display fake progress indicators or claim that an AI operation has succeeded when it has not.

When a mock generator is being used, label it clearly as a demonstration feature.

### 7.4 FIR Draft Page

The FIR draft must be presented as a document requiring human review.

Use a clean document-like layout with:

- A clear draft title.
- Complaint reference information where available.
- Readable paragraphs.
- Appropriate spacing.
- An editable text area.
- A visible draft status.
- Clear actions to save or update the draft, where implemented.

Display the following label when appropriate:

"AI-Generated FIR Draft — Pending Human Review"

Distinguish generated text from the original complaint when both are displayed.

Do not make the draft look like an officially registered FIR.

### 7.5 Police Review Page

The police review interface should prioritize clarity and efficient review.

Display the following information in a logical order:

1. Complaint details.
2. Original complaint description.
3. Generated FIR draft.
4. Editable draft content.
5. Reviewer comments, where implemented.
6. Current review status.
7. Available review actions.

Make the draft's current status easy to identify.

Use clear action labels such as:

- Save Changes.
- Approve Draft.
- Return for Correction.

Approval must refer only to the prototype's review workflow, not official FIR registration.

Use confirmation feedback for important status changes.

Do not show actions that have not been implemented.

## 8. Buttons and Interactive Elements

Use consistent button styles.

### Primary Button

- Navy background.
- White text.
- Clear label.
- Consistent padding and corner radius.

Use for the main action on a page, such as submitting a complaint or generating a draft.

### Secondary Button

- White or light background.
- Navy text.
- Subtle border.

Use for actions such as editing or returning to a previous step.

### Destructive or Important Actions

Use restrained warning or error styling when necessary.

Do not make every button visually prominent.

All interactive controls must have clear labels and visible focus states where supported.

Ensure that buttons have sufficient size and spacing for comfortable use.

## 9. Form Design and Validation

Forms must be easy to understand and complete.

Requirements:

- Place labels consistently above or beside fields.
- Clearly indicate required fields.
- Use suitable date and contact input controls.
- Provide short, useful helper text where necessary.
- Show validation errors near the relevant input or in a clearly visible error area.
- Preserve user input when validation fails.
- Use clear success and error feedback.
- Avoid technical error messages that ordinary users cannot understand.

Do not use colour alone to communicate an error.

Use accessible labels and logical keyboard navigation wherever supported by the framework.

## 10. AI Transparency and Status Communication

The interface must communicate the role of AI honestly.

Clearly distinguish between:

- Original complaint information.
- AI-generated draft content.
- Content edited by a human reviewer.
- A draft pending review.
- A draft marked approved within the demonstration workflow.
- A draft returned for correction.

Do not imply that AI output has been verified merely because it has been generated.

Do not present model confidence, similarity scores, legal conclusions, or verification indicators unless they are actually computed and their meaning is clearly explained.

Use concise explanatory text to remind users that generated content requires human review.

## 11. Accessibility and Multilingual Support

Design the interface for users with different levels of technical knowledge.

Requirements:

- Maintain readable text sizes.
- Use sufficient contrast between text and backgrounds.
- Provide clear field labels.
- Avoid colour-only status indicators.
- Support keyboard navigation where practical.
- Ensure that Malayalam and Hindi text displays correctly.
- Allow long text to wrap naturally.
- Avoid fixed-width layouts that break on smaller screens.
- Ensure that important actions are not accessible only through hover interactions.

Do not translate legal terminology mechanically without considering its meaning and context.

## 12. Cards, Borders, and Surfaces

Use cards and bordered sections only when they help organize information.

Preferred appearance:

- White content surfaces.
- Subtle grey borders.
- Small or moderate corner radii.
- Consistent internal padding.
- Minimal shadows, if any.

Avoid excessive nested cards, thick borders, strong gradients, and decorative backgrounds.

Use separators and whitespace to organize content.

## 13. Icons and Visual Elements

Use simple, recognizable icons only when they improve understanding.

Icons must not replace important text labels.

Avoid:
- Decorative police badges.
- Government emblems.
- Official-looking seals.
- Unnecessary illustrations.
- Random emojis used as interface elements.
- Images that imply official affiliation.

Prefer a restrained and consistent icon style.

## 14. Responsive Design

The application should remain usable on desktop, tablet, and mobile screens.

On smaller screens:

- Stack multi-column sections vertically.
- Allow form fields to use the available width.
- Prevent horizontal scrolling wherever practical.
- Keep buttons large enough to interact with comfortably.
- Allow long complaint descriptions and drafts to wrap naturally.
- Ensure that navigation remains understandable.

Use the responsive capabilities of Streamlit instead of introducing unnecessary frontend frameworks.

## 15. Streamlit-Specific Guidelines

The initial application uses Streamlit.

Therefore:

- Prefer Streamlit's native components where suitable.
- Use `st.set_page_config` appropriately.
- Organize content with headings, containers, columns, forms, and tabs where they improve usability.
- Avoid excessive custom CSS.
- If custom CSS is required, keep it minimal and centralized.
- Do not use fragile CSS selectors that depend on undocumented Streamlit internals.
- Preserve keyboard accessibility and normal control behaviour.
- Ensure that visual styling does not interfere with Streamlit form submission, session state, or reruns.

The design should be achievable using the chosen technology stack without unnecessary complexity.

## 16. Consistency Rules

Apply the same design decisions throughout the application.

Maintain consistency in:

- Colours.
- Typography.
- Heading hierarchy.
- Spacing.
- Button appearance.
- Input fields.
- Status labels.
- Card and border styles.
- Error and success messages.
- Navigation labels.

Do not introduce new colours, font styles, or component patterns without a clear reason.

If a new component is required, style it consistently with the existing interface.

## 17. Design Review Checklist

Before considering a page complete, check the following:

- Is the page clean and professional?
- Is the purpose of the page immediately understandable?
- Are all form labels readable?
- Are the main actions obvious?
- Is the colour palette consistent?
- Does Malayalam text display correctly?
- Are validation messages easy to understand?
- Are draft and review statuses clearly distinguishable?
- Is AI-generated content labelled honestly?
- Does the interface avoid implying official government affiliation?
- Does the layout work on smaller screens?
- Are there unnecessary decorative elements?
- Does the page avoid displaying features that are not implemented?

Fix significant usability or consistency issues before completing the page.

## 18. Final Design Principle

The application must be professional, accessible, transparent, and easy to use.

Visual design must support the primary goal: helping citizens submit complaints and enabling human reviewers to inspect AI-generated Malayalam FIR drafts.

Clarity, readability, accessibility, and trustworthiness take priority over decoration.

Follow these guidelines throughout the project and consult them whenever creating or modifying the user interface.
