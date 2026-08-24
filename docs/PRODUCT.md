# PRODUCT.md
## Purpose
This document is the authoritative product north star for the hackathon.
It answers: **What are we building, and what should it feel like to use?**
If implementation pressure conflicts with this document, raise the conflict rather than silently redefining the product.

**This is product intent, not a description of what is built.** For the shapes
and behaviour that exist today, read `TUTOR_AGENT.md`. Where this document
names something unbuilt, it says so.

## 1. Product Thesis
We are building a **persistent, course-aware AI whiteboard tutor**.
The product should feel less like a chatbot and more like a knowledgeable tutor sitting beside the student, looking at the same piece of paper, understanding the student's actual course, and writing directly alongside them.
The differentiator is not merely "AI can answer homework questions."
It is:
> AI understands the student's course, watches how the student is solving, and teaches spatially on the same whiteboard.
The canvas is not an attachment to the AI experience. The canvas **is** the AI experience.

## 2. Product Hierarchy
```text
Courses / Spaces
      ↓
Saved Whiteboard Sessions
      ↓
Infinite Whiteboard
```
A course/space might be `MATH 101`, `PHYS 101`, `Calculus I`, or `Interview Prep`.
A course is a persistent learning context containing course materials, course-specific AI context, instructor-style signals, saved whiteboards, and eventually student analytics.
When the student enters a course, they see a grid of previous whiteboard sessions plus an option to create a new one.

## 3. Persistent Sessions
A whiteboard session is a persistent working document, not a disposable prompt.
If a student stops halfway through on Monday and returns Tuesday, reopening the session should restore the work naturally.
Preserve:
- student handwriting
- AI writing and marks
- problem content
- imported/reconstructed content
- canvas objects
- useful tutoring context
- useful viewport state
The desired feeling is **reopening a notebook**, not reopening a conversation.
Session cards may use preview images, but the saved interactive canvas state is the source of truth.

## 4. Canvas-First Interaction
There is no conventional chat interface in the core vision.
The user should not need to move between whiteboard and chatbot to work with the tutor.
User inputs include:
- handwriting
- drawing
- selecting regions
- importing problems
- tutor action buttons
- optional voice
- generation controls
AI outputs include:
- checks/crosses
- circles/arrows
- underlines/highlights
- short notes
- math expressions
- visual explanations
- clean problem text
A good interaction:
```text
student writes an incorrect step
        ↓
AI identifies exact region
        ↓
AI circles the relevant sign
        ↓
AI writes "check this sign"
```
Avoid turning every interaction into a paragraph in a side panel.

## 5. Two Core Problem Entry Flows
### 5.1 AI-Generated Practice
```text
Open course
   ↓
New whiteboard
   ↓
Generate practice problem
   ↓
Course Context shapes generation
   ↓
Problem appears cleanly/typeset
   ↓
Student solves
```
Generated questions should feel like they belong to the student's actual course whenever possible.
### 5.2 Student-Provided Problem
Potential inputs:
- photo
- screenshot
- image
- PDF
- pasted content
- copied problem region
Intended flow:
```text
student imports source
        ↓
AI interprets source
        ↓
system reconstructs problem cleanly
        ↓
clean problem appears on whiteboard
        ↓
student solves
```
The product should not stop at placing a screenshot on the canvas.
The goal is to normalize outside questions into the whiteboard environment.

## 6. Course Context
Course Context is more than generic RAG.
Possible source materials:
- lecture slides/notes
- assignments
- labs/worksheets
- syllabi
- formula sheets
- practice exams
- old exams
- instructor examples
- individual uploaded questions
The system should learn:
- covered and not-yet-covered topics
- how concepts are presented
- terminology and notation
- expected solution style/rigor
- instructor wording
- formatting conventions
- typical difficulty
- common question structures
- topic distribution
- authentic examples
Course Context informs both tutoring and question generation.
The target is understanding **what MATH 101 means for this student**, not just knowing calculus.

## 7. Instructor-Style Matching
If a student uploads multiple exams, the system should infer:
- wording
- notation
- layout
- difficulty
- expected response length
- subquestion patterns
- scaffolding level
- conceptual/computational balance
- common topic combinations
Generated practice should aim to feel like:
> This could plausibly have appeared on my professor's exam.
Generate new questions rather than reproducing uploads.
Users should be able to adjust defaults, e.g.:
```text
Same instructor style
Harder / easier than usual
Midterm / final difficulty
Focus on Chapter 6
Focus on a topic
More conceptual
More computational
```

## 8. Course Boundaries
The tutor should distinguish between what the model knows and what this course appears to have taught.
If it wants to use a technique not found in course materials, it should not silently introduce it.
Intended flow:
```text
AI identifies useful technique
        ↓
technique appears outside course context
        ↓
AI pauses and explains:
"This approach uses integration by parts, which I don't
see in your course material yet."
        ↓
user chooses:
Stay within course material
Continue with this technique
```
The exact confidence mechanism may evolve. Prefer transparency when uncertain.

## 9. Tutor Controls
Core actions:
```text
Mark
Hint
Explain
I'm Stuck
```
These are distinct tutoring behaviors, not different labels for a generic prompt.

## 10. Mark
Purpose: **Evaluate what I have done so far.**
Expected behavior:
- inspect current work
- identify correct/incorrect portions
- mark relevant regions spatially
- recognize partial progress
- avoid solving future steps unnecessarily
Examples:
```text
✓ beside a correct line
circle an incorrect sign
underline a suspicious term
"missing chain rule"
"recheck this substitution"
```
Mark should feel like a tutor/TA reviewing the page, not generating a worked solution.

## 11. Hint
Purpose: **Help me progress without taking the problem away from me.**
Use the smallest useful intervention.
Prefer `"What should u be here?"` over directly supplying `u` if the smaller nudge is sufficient.
Hint may point, underline, ask a targeted question, remind the student of a covered concept, or direct attention to a previous line.
It should generally not provide the full next step.

## 12. Explain
Purpose: **Help me understand this concept, line, or mistake.**
Explain can be more detailed than Hint.
It should use selected canvas context when available, annotate relevant pieces, use course notation, and tie the explanation to what the student actually attempted.
It should remain grounded in the current whiteboard rather than defaulting to a generic lecture.

## 13. I'm Stuck
Purpose: **I need a stronger intervention.**
This mode may identify the next meaningful step, write part of that step, suggest the method, or provide enough scaffolding to restart reasoning.
It is intentionally more interventionist than Hint, but should avoid needlessly completing the entire problem.

## 14. Select for AI
Users need a direct way to point the tutor at part of the board.
They should be able to select an equation, line, diagram, region, or related shapes, then choose a tutor action or use voice.
The AI should receive the selected region plus the full problem, surrounding canvas, course context, and relevant prior tutor state.
Users should not need to describe visual locations in words.

## 15. Voice
Voice is a contextual input mechanism, not a separate chatbot.
Example:
```text
select equation
   ↓
press microphone
   ↓
"Why can't I do this?"
   ↓
AI receives transcript + selection + problem + canvas + course
   ↓
AI responds on canvas
```
Do not architect voice as disconnected speech-to-chat.

## 16. Live Tutor
An optional live tutor can watch progress and intervene automatically.
The user controls its "jumpiness":
### Instant
Most proactive. React essentially immediately when a meaningful issue/opportunity is detected.
### 2 Seconds
Wait roughly two seconds of inactivity before considering intervention.
### New Line
Least intrusive. Wait until the student appears to move to a new line/step/region before evaluating the previous work.
These are behavioral settings, not cosmetic labels.
A hackathon approximation is acceptable if the semantics remain clear.

## 17. Canvas Layers
The board should feel like one shared notebook by default.
Internally distinguish:
```text
System / problem content
Student-created content
AI tutor content
```
This enables:
- analyze student work without confusing AI output
- hide/clear AI feedback
- undo tutor interventions
- preserve problem content
- advanced layer controls later
An advanced UI might eventually expose:
```text
☑ Problem
☑ My Work
☑ Tutor
```
but normal users should not have to think about layers.

## 18. AI Rendering Philosophy
The tutor decides **what** to communicate; the renderer decides **how** it appears.
```text
Tutor intent
    ↓
structured annotation/action
    ↓
canvas renderer
    ↓
tldraw shapes / text / math
```
Do not tightly couple reasoning to one visual style.

## 19. Structured Canvas Actions

Implemented today — the authoritative list is `backend/app/schemas/tutor.py`:

```text
text     say something at a point
circle   point at a region
check    mark a region right
cross    mark a region wrong
```

`math`, `arrow`, `underline`, and `highlight` were specified earlier and are
**not built**. Circling, underlining, and highlighting were three ways to say
"look here", and a labelled mark duplicated `text`, so one pointing primitive
carries all of it. Add one back only if the tutor demonstrably cannot express
something; the renderer and the prompt must change together.
Model output must be validated before rendering.
The model should not directly call arbitrary canvas methods.

## 20. Clean Math First, Handwriting Later
For the MVP, prioritize structured/typeset math and predictable text.
A polish goal is realistic AI handwriting, including animated pen strokes and natural drawing motion.
Treat handwriting as a renderer/presentation improvement so tutor reasoning does not need to be rewritten later.

## 21. Infinite Canvas
Each whiteboard session is conceptually an infinite canvas.
A new problem normally begins in a new session within the same course.
Do not redesign around fixed notebook pages unless the team intentionally changes this decision.

## 22. Rich Student Model
Long term, the product should model how the student thinks, not just topic percentages.
Potential observations:
```text
Frequently loses negative signs during algebra.
Usually chooses the right technique but struggles with final simplification.
Frequently forgets constants of integration.
Needs fewer hints on related-rates problems than last week.
Often starts calculating before identifying the relevant theorem.
Recognizes mistakes quickly after visual nudges.
```
This can eventually influence question selection, difficulty, hint style, intervention timing, explanation depth, recurring-error detection, and review recommendations.

## 23. Student Model: Hackathon Scope
Do not let sophisticated personalization block the core loop.
A simple MVP may track:
- attempted topics
- correct/incorrect attempts
- hints used
- repeated mistake tags
- difficulty
- session history
That is enough to demonstrate that the system is beginning to learn how the student studies.

## 24. Analytics
Later analytics should favor meaningful insights over one opaque mastery score.
Examples:
```text
"You've improved on substitution across your last 8 attempts."
"Most errors this week are algebraic rather than conceptual."
"You solve product-rule questions correctly without hints."
```
This is later-stage product work.

## 25. Built-In Course
The demo should work without requiring judges to upload files.
At least one built-in course, likely Calculus I, should provide sample context, style, questions, and reliable tutoring scenarios.
Where practical, built-in courses should use the same underlying mechanisms as uploaded courses.

## 26. Import Reconstruction
Imported questions should preserve meaning and wording as faithfully as practical.
For math, reconstruction may include text recognition, mathematical notation, equations, and diagrams where feasible.
The result should be clean canvas content the student can immediately work beside.

## 27. Problem Ownership
Problem/system content should be distinguishable from student and AI content.
The tutor should know:
```text
what the problem said
what the student wrote
what the AI wrote
```
Provide structured problem content separately from images when possible.

## 28. Tutor Context
A strong tutor request may include:
```text
course
course context
current problem
canvas snapshot
student shapes
system shapes
AI shapes
selected region
tutor mode
recent tutor interactions
student model
```
Not every request needs every field.
Give the tutor enough structured context that it does not have to infer everything from one screenshot.

## 29. Multimodal Interpretation
Traditional OCR is not assumed to be the core strategy.
For the MVP:
```text
canvas snapshot + metadata
        ↓
multimodal model
        ↓
interpret student work
```
Add dedicated OCR only if experiments show clear value.
Do not turn the project into an OCR research project unless necessary.

## 30. Human-Tutor Mental Model
When choosing UX behavior, ask what a good human tutor beside the student would do.
Usually they would:
- inspect current work
- understand the student's intent
- point to the exact relevant part
- avoid taking over too quickly
- adjust help based on how stuck the student is
- use course terminology
- remember recurring problems
- let the student remain in control

## 31. Restraint Is a Feature
More explanation is not always better.
Hint should be smaller than Explain.
Mark should not reveal future steps unnecessarily.
I'm Stuck can be more direct.
Live tutor must respect the chosen intervention threshold.
Student control is part of the product.

## 32. Product Anti-Goals
We are **not** building:
- a generic chatbot with a whiteboard attached
- a generic PDF-RAG app
- an OCR demo
- a grading-only app
- a static worksheet generator
- a custom graphics engine
- a complete LMS
RAG, OCR, generation, and grading are tools in service of the tutoring experience.

## 33. 60-Second Demo North Star
```text
1. Open MATH 101.
2. Show that the course knows uploaded material.
3. Generate a new professor-style practice problem.
4. Clean unseen problem appears on the whiteboard.
5. Student solves by hand.
6. Student makes an intentional mistake.
7. Tutor identifies the exact handwritten region.
8. Tutor marks it directly on the canvas.
9. Tutor gives a restrained hint.
10. Student fixes the mistake.
11. Session persists.
12. Optionally show that useful student-learning information was recorded.
```
This flow should drive prioritization.

## 34. Secondary Demo: Import
```text
photo/screenshot of real problem
    ↓
import
    ↓
clean reconstruction
    ↓
student writes
    ↓
tutor works exactly as with generated problems
```

## 35. Secondary Demo: Select for AI
```text
select one step
    ↓
Explain
    ↓
AI focuses on that exact region
    ↓
local visual explanation
```

## 36. Secondary Demo: Course Boundary
If reliable:
```text
tutor wants untaught technique
    ↓
notices it is outside course context
    ↓
asks permission before continuing
```
This is distinctive but should not jeopardize the main demo.

## 37. MVP Priorities
Prioritize:
1. course/space organization
2. saved whiteboard sessions
3. tldraw infinite canvas
4. session restore
5. clean problem rendering
6. AI-generated practice
7. imported problem reconstruction
8. course ingestion
9. course-aware generation
10. canvas capture
11. handwriting interpretation
12. structured annotations
13. Mark / Hint / Explain / I'm Stuck
14. Select for AI
15. reliable iPad/browser behavior
16. end-to-end integration

## 38. Important but Simplifiable
May be implemented minimally:
- live tutor
- voice
- basic mastery tracking
- basic analytics
- advanced style inference
- sophisticated retrieval
- advanced layer UI
- many built-in courses
- complex settings

## 39. Future / Polish
Keep on the roadmap:
- realistic AI handwriting
- animated pen strokes
- sophisticated long-term student model
- deeply adaptive practice
- analytics dashboards
- richer voice interaction
- advanced layer controls
- stronger instructor-style modeling
- review planning

## 40. Product Decision Heuristics
Prefer designs that feel like a tutor sharing the student's workspace.
Prefer:
- spatial feedback
- direct manipulation
- continuity
- course grounding
- restrained hints
- student control
- local context
- persistent work
Avoid:
- walls of prose
- generic tutoring disconnected from the course
- contextless responses
- excessive interruption
- AI taking over
- forcing visual context into text descriptions

## 41. Ultimate Product Loop
```text
Student opens their real course
        ↓
AI understands that course
        ↓
Student opens a persistent whiteboard
        ↓
Student imports or generates a problem
        ↓
Student works naturally
        ↓
Tutor observes the work
        ↓
Tutor responds at the right time and place
        ↓
Student continues
        ↓
Session persists
        ↓
System learns how this student thinks
        ↓
Future tutoring becomes more personalized
```
That is the product north star.
