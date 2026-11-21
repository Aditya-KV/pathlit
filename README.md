# Pathlit

**An AI teacher that sits next to your cursor in Blender.** It points at the next thing to click, speaks one short line, and checks that
you really did it before moving on. If you prefer, it can also click for you.

![Pathlit teaching Blender: a pointer on the Mesh item, a speech bubble and the control panel](docs/images/demo_teach.jpg)

> Pathlit teaches Blender 4.1 on Windows. It was built as a course project (Microsoft AI-901 topics) under the working name *Shifu*.
> Status: working prototype. See [Project status](#project-status) for what is measured and what is not yet.
>
> *The picture above is the real pointer, bubble and control panel drawn over a Blender-only screenshot
> (see [Demo](#demo) for how the pictures are made).*

---

## Contents
1. [What it does](#what-it-does)
2. [Demo](#demo)
3. [Three modes](#three-modes)
4. [Architecture](#architecture)
5. [How Pathlit uses Azure](#how-pathlit-uses-azure)
6. [Quick start](#quick-start)
7. [Configuration](#configuration)
8. [Using Pathlit](#using-pathlit)
9. [Typed tasks ("build a house")](#typed-tasks-build-a-house)
10. [Show me and Do it: the safety model](#show-me-and-do-it-the-safety-model)
11. [Privacy](#privacy)
12. [Command reference](#command-reference)
13. [Testing and evaluation](#testing-and-evaluation)
14. [Project status](#project-status)
15. [Troubleshooting](#troubleshooting)
16. [Project layout](#project-layout)
17. [Design decisions](#design-decisions)
18. [Limitations](#limitations)
19. [Credits and licences](#credits-and-licences)

---

## What it does

Blender's screen is crowded and video tutorials cannot see where you are stuck. Chat assistants cannot see your screen at all.
Pathlit watches Blender only when you interact with it, and walks you through a task one small step at a time:

- **8 built-in lessons**, starting with "Model a donut" (9 steps), then edit mode, workspaces, sculpting, lights and cameras, duplicating, object properties and render settings.
- **It follows you.** Press the start key once, then just click in Blender. After each click Pathlit checks the step; if you did it, a pointer glides to the next target and a short line is spoken. If you are mid-step (a menu is open, a second click is still to come) it stays quiet.
- **It checks your work.** Screen text is read by Azure Vision, and a small Blender add-on reports the mode, objects, modifiers and each object's location, rotation and scale, so "Scale Z = 1.5" is verified, not assumed.
- **You can ask for your own task.** Type "a simple house" and Pathlit plans the steps, checks the plan, and teaches (or builds) it.
- **It can do the work.** *Show me* clicks each step while you watch. *Do it* finishes the whole task itself, under strict safety rules.

The pointer is a small cursor-shaped overlay that glides between targets with easing, pulses on arrival, and fades when you click what it
points at. The overlay and the control panel are excluded from screen capture, so their text is never read as part of Blender's screen.

## Demo

**Teach me.** The pointer lands on the target (here the *Mesh* item of the Add menu), a bubble says what to do, one short line is spoken,
and the panel on the right ticks steps off as you go. Pathlit never moves your mouse in this mode.

![Teach me mode](docs/images/demo_teach.jpg)

**Do it.** In the mode where Pathlit clicks for you, a red border and a banner are on screen the whole time, and **Esc** stops it at once.

![Do it mode with the red control border and banner](docs/images/demo_do_it.jpg)

**The control panel**, in its states (a dark, quiet design in the style of shadcn/ui: a tab-style mode switch, an input with suggestions,
a progress bar, steps that check off, and one main button showing the hotkey):

| Teach me | Show me | Do it |
|:---:|:---:|:---:|
| ![Teach me](docs/images/panel_teach.png) | ![Show me](docs/images/panel_show.png) | ![Do it](docs/images/panel_do.png) |

| Planning a typed task | Task finished | Collapsed |
|:---:|:---:|:---:|
| ![Planning](docs/images/panel_planning.png) | ![Done](docs/images/panel_done.png) | ![Collapsed](docs/images/panel_collapsed.png) |

> **How these pictures are made.** `python scripts/make_readme_images.py` renders the real control panel and the real overlay code off-screen
> and draws them over `tests/data/screens/blender_09.png`, a screenshot that contains only Blender. Pathlit's own screenshots are never saved,
> and the script never captures your desktop.

## Three modes

| Mode | What Pathlit does | Default |
|---|---|---|
| **Teach me** | Points and speaks. You click. Pathlit never moves the mouse. | yes |
| **Show me** | Moves the real cursor to the target, waits for your OK (the start key), clicks, narrates. | no |
| **Do it** | Does the whole task with a countdown before every action. | no |

Switch modes with the tabs in the panel or the tray icon (blue = Teach me, amber = Show me, red = Do it). Show me and Do it start
only when **you** choose them and press the start key. Esc stops everything instantly. Details in
[the safety model](#show-me-and-do-it-the-safety-model).

---

## Architecture

### The big picture

Pathlit is a desktop app on your PC. Two cloud services are used for the senses (Azure reads the screen text and speaks), one for the words
(Groq writes the short explanations and plans), and a small add-on inside Blender reports what Blender itself knows.

```mermaid
flowchart TB
    subgraph PC["Your Windows PC"]
        direction TB
        subgraph APP["Pathlit app (Python, PyQt6)"]
            direction TB
            ACT["Activity listener<br/>pynput, listen only"]
            HK["Hotkeys<br/>start key, Esc"]
            CTL["Controller<br/>one cycle per click"]
            CAP["Screen capture<br/>mss, memory only"]
            MATCH["Target matcher<br/>rapidfuzz"]
            ENG["Lesson engine<br/>and step checks"]
            TCH["Teacher and planner<br/>text only"]
            OVL["Overlay<br/>pointer, bubble, banner"]
            PNL["Control panel"]
            AUTO["Executor and Guard<br/>Show me / Do it"]
            SKL[("Skill map<br/>SQLite")]
        end
        BL["Blender 4.1<br/>with the Pathlit add-on<br/>HTTP on 127.0.0.1"]
        MIR["Mirage<br/>local text reader, fallback"]
        MSE["Real mouse<br/>pyautogui, loaded only when needed"]
    end
    subgraph AZ["Microsoft Azure"]
        VIS["Computer Vision<br/>Image Analysis 4.0, Read"]
        SPE["Speech<br/>neural text to speech"]
    end
    GRQ["Groq<br/>gpt-oss models"]

    ACT --> CTL
    HK --> CTL
    CTL --> CAP
    CAP -->|"JPEG of the Blender screen"| VIS
    VIS -->|"words and boxes"| MATCH
    CAP -.->|"if Azure fails"| MIR
    MIR -.-> MATCH
    CTL <-->|"GET /state, POST /do"| BL
    MATCH --> ENG
    BL --> ENG
    ENG --> OVL
    ENG --> SKL
    ENG -->|"step text and screen words only"| TCH
    TCH <-->|"text only"| GRQ
    TCH --> SPE
    SPE -->|"audio"| TCH
    ENG --> PNL
    CTL --> AUTO
    AUTO -->|"direct action"| BL
    AUTO -->|"cursor click"| MSE
```

The idea that shapes everything: **the language model only writes words.** Code decides whether a step passed, and where the pointer
goes. The model never sees an image and never gives coordinates; a target is named by its on-screen text and found by the screen reader.

### One cycle, step by step

A "cycle" runs after a click in Blender (auto-advance) or when you press the start key.

```mermaid
sequenceDiagram
    autonumber
    participant U as You
    participant C as Controller
    participant S as Screen capture
    participant V as Azure Vision
    participant B as Blender add-on
    participant K as Step check
    participant E as Lesson engine
    participant T as Teacher (Groq)
    participant P as Azure Speech
    participant O as Overlay

    U->>C: click in Blender (or press the start key)
    C->>C: wait for the screen to settle (0.25 s)
    par at the same time
        C->>S: capture the Blender window
        S->>V: JPEG, longest edge 2048 px
        V-->>C: lines, words and boxes
    and
        C->>B: GET /state
        B-->>C: mode, objects, modifiers, transforms
    end
    C->>K: run the check for the step shown last
    alt passed
        K-->>E: advance (or catch up if you ran ahead)
        E->>C: next step
        C->>C: find the next target's text on screen
        C->>O: glide the pointer there, show the bubble
        C->>T: step text and on-screen words (no image)
        T-->>C: one or two short sentences
        C->>P: speak the line
        P-->>U: audio
    else not yet
        K-->>C: stay quiet, look once more a moment later
    end
```

Measured on a saved screenshot with real Azure and Groq: the pointer is ready about **0.9 s** after a check starts, and the first spoken word
arrives at a median of about **2.2 s** (target: 3 s).

### How a step is checked (code decides, not the model)

```mermaid
flowchart LR
    STEP["Current step"] --> KIND{"check kind"}
    KIND -->|screen_text_present| A["Is this text on the screen<br/>(Azure Vision words)"]
    KIND -->|blender_state| B["Mode, active object, modifier,<br/>object count, location / rotation / scale<br/>(Blender add-on)"]
    KIND -->|clicked_target| C["Did your click land<br/>on the target's box"]
    KIND -->|none| D["Always passes"]
    B -. "add-on missing" .-> F["fallback_text on screen<br/>or reported as unverified"]
    A --> R{"passed?"}
    B --> R
    C --> R
    D --> R
    R -->|yes| ADV["Advance, point at the next target"]
    R -->|no| WAIT["Stay quiet, look again once,<br/>nudge after 20 s of silence,<br/>hint after two misses"]
```

### Show me and Do it: how an action is allowed

```mermaid
flowchart TD
    REQ["Next action for the step"] --> MODE{"mode"}
    MODE -->|Teach me| STOP0["Never moves anything"]
    MODE -->|Show me or Do it| GUARD{"Guard"}
    GUARD -->|"Esc pressed, mouse moved more than 50 px,<br/>wrong window in front, rate or count limit"| HALT["Stop and say why"]
    GUARD -->|"clicking a dangerous label<br/>(Save, Delete, Export, Quit...)"| HALT
    GUARD -->|allowed| KIND{"action type"}
    KIND -->|"direct (add a torus, set Scale Z)"| ADDON["POST /do to the add-on<br/>validated again inside Blender"]
    KIND -->|"cursor click"| MOVE["Warning pointer, countdown,<br/>move the real cursor, click"]
    ADDON --> CHECK["Run the step check"]
    MOVE --> CHECK
    CHECK -->|passed| NEXT["Next step"]
    CHECK -->|failed| HALT
    NEXT --> LOG[("logs/actions.csv")]
```

### What leaves your computer

| Data | Goes to | Why |
|---|---|---|
| A JPEG of the Blender window (about a second in memory, never saved) | Azure Computer Vision | reading the on-screen text |
| One short piece of text (the step, a list of on-screen words, Blender's state) | Groq | writing the spoken line, or planning a typed task |
| The sentence to be spoken | Azure Speech | text to speech |
| Mouse and keyboard activity | nowhere | the listener only notes *that* you clicked, and where |
| Blender's scene state | nowhere (localhost only) | step checks |
| Skill map, logs, timings | nowhere | progress and measurements |

### Where each part lives

| Part | Module | Job |
|---|---|---|
| Controller | `src/pathlit/controller.py` | the cycle, auto-advance triggers (debounce, second look, idle nudge, catch-up) |
| Perception | `src/pathlit/perception/` | `azure_vision` (primary), `mirage_reader` (local fallback), `router`, `target_match` |
| Lessons | `src/pathlit/lessons/` | JSON loader (pydantic), step engine, code-decided checks |
| Brain | `src/pathlit/brain/` | `teacher`, `planner`, `builder` (exact numbers), `vocabulary`, `docs_search` |
| Control | `src/pathlit/control/` | allow-list, `guard`, mouse, `executor` (Show me / Do it) |
| Overlay | `src/pathlit/overlay/` | pointer, bubble, banner, exclusion from capture |
| Panel | `src/pathlit/ui/panel.py` | the control panel |
| Voice | `src/pathlit/voice.py` | Azure Speech |
| Blender add-on | `blender_addon/pathlit_bridge/` | read-only state, allow-listed `POST /do` |

---

## How Pathlit uses Azure

Pathlit uses two Azure AI services in production (**Computer Vision** for reading the screen and **Speech** for the voice), has code for a
third (**AI Search**, optional and not deployed), and could not use a fourth (**Azure OpenAI**). Here is each one, what it does, and why.

| Service | Azure resource | Used for | Where in the code | `.env` keys | Tier | If it fails |
|---|---|---|---|---|---|---|
| **Computer Vision** (Image Analysis 4.0, Read) | Computer Vision | reading every word on the Blender screen, with boxes | `perception/azure_vision.py` | `AZURE_VISION_ENDPOINT`, `AZURE_VISION_KEY` | Free (F0), East Asia | falls back to local Mirage |
| **Speech** (neural text to speech) | Speech | the spoken line (voice `en-US-JennyNeural`) | `voice.py` | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Free (F0), East Asia | the line is shown, not spoken |
| **AI Search** (optional) | Azure AI Search | Blender manual excerpts for the teacher | `brain/docs_search.py`, `scripts/build_docs_index.py` | `AZURE_SEARCH_*` | **not deployed** (cost) | the teacher uses the lesson text only |
| **Azure OpenAI** | none | would have been the teacher | `.env` keys left empty | `AZURE_OPENAI_*` | **unavailable** on the student subscription | Groq is used instead |

### 1. Azure Computer Vision: how the screen becomes "targets"

Pathlit needs to know **where the words are**, because a target in a lesson is named by its text ("Mesh", "Subdivision Surface"), not by a
pixel coordinate. Azure's **Read** feature (OCR in Image Analysis 4.0, SDK `azure-ai-vision-imageanalysis`) does this well on Blender's
dense, small-font interface.

```mermaid
flowchart LR
    A["Screenshot<br/>mss, DPI-aware, memory only"] --> B["Downscale to 2048 px<br/>longest edge, remember the factor"]
    B --> C["JPEG, quality 85"]
    C --> D["ImageAnalysisClient.analyze<br/>VisualFeatures.READ"]
    D --> E["blocks, lines, words<br/>with polygons and confidence"]
    E --> F["report_from_result<br/>polygons to boxes, scaled back<br/>to real screen pixels"]
    F --> G["ScreenReport<br/>list of Element: text, box, confidence"]
    G --> H["target_match<br/>rapidfuzz, standalone-label preference,<br/>nearest to the previous target"]
    H --> I["Pointer position"]
    G --> J["screen_text_present checks"]
    G --> K["words given to the teacher<br/>as text"]
```

- **What is sent:** one JPEG of the Blender window, quality 85, longest edge 2048 px. Measured against the full-size PNG: a 4x smaller upload,
  a read in about **0.9 s instead of 1.7 s**, and the same 16 of 16 test targets found. Nothing is stored by Pathlit; the image exists in memory for about a second.
- **What comes back:** blocks, then lines, then words, each with a bounding polygon and a confidence. Pathlit turns each line and each word into an
  `Element` (text, box in real pixels, confidence). Words let it point at one item of a line; lines let it match multi-word labels
  ("Subdivision Surface").
- **Matching a target:** a lesson step says `target_text: "Mesh"`. The matcher does fuzzy matching (rapidfuzz), ignores noise tokens shorter than
  3 letters, prefers a **standalone** label over the same word inside a longer one ("Object" the menu, not "Object Mode"), and prefers the match
  **nearest the previous target** ("Camera" in the open Add menu, not the Camera object in the Outliner).
- **Why Azure first, and a local fallback second.** The first plan was local-first with Mirage. Measured on 10 real Blender screens:

  | Reader | Text lines found per screen | Target words located |
  |---|---|---|
  | Azure Vision Read | 94 to 128 | the primary reader (16 of 16 test targets) |
  | Mirage (local) | 11 to 30 | 2 of 100 |

  So the order was reversed. Mirage stays as the offline fallback: if Azure is unreachable or rate-limited, the `Router` switches to it and the lesson carries on.
- **Warm-up and limits.** The first call is slow, so a blank image is sent at start-up. The free tier allows about 20 calls a minute, which is why
  auto-advance debounces clicks (0.25 s), takes one second look, and never polls on a timer.
- **Cost of a lesson.** Roughly one call per click, so a 9-step donut lesson is about 10 to 20 calls, well inside the free tier.

### 2. Azure Speech: the voice

Text to speech with the neural voice `en-US-JennyNeural` (SDK `azure-cognitiveservices-speech`).

- One synthesizer and one connection are kept **warm**, and audio **streams to the speaker as it is produced**, so the first word is heard at a
  median of about 2.2 s after a check starts (screen read, Blender state, the teacher's sentence and the first audio chunk all included).
- Lines are capped at two sentences, about 30 words, so the voice never reads a paragraph.
- **Esc** stops speech immediately (`stop_speaking_async`).
- If Speech fails the lesson continues in silence and the bubble still shows the line.

### 3. Azure AI Search (optional, not deployed)

The code, the index builder (`scripts/build_docs_index.py`) and the manual downloader (`scripts/fetch_manual.py`) exist and are tested with fakes. The idea is
to give the teacher two or three excerpts of the Blender manual (CC BY-SA 4.0) so its explanation is grounded in documentation.
**No Search resource exists**: its default paid tier was estimated at about **$250 a month**, which is far beyond a student project. Pathlit runs fine without it.
A local search over the downloaded manual would be the zero-cost alternative (listed under [Project status](#project-status)).

> **Warning for anyone setting this up:** do not create Azure AI Search on a paid tier by accident. It is optional.

### 4. Azure OpenAI (not used) and why Groq is the teacher

The original design used Azure OpenAI for the teacher. On the student subscription, deployments failed in every allowed region ("unsupported region", then a
policy block, `RequestDisallowedByAzure`), and non-OpenAI catalogue models were not deployable either. The teacher is therefore **Groq** (`openai/gpt-oss-120b` for
planning, `openai/gpt-oss-20b` for the spoken lines), behind a small interface (`brain/teacher.py`) that also supports "no model": lessons then speak their own text.
Groq receives **text only**. Moving back to Azure OpenAI later needs only a new client behind the same interface.

### 5. Setting the Azure resources up

1. Create one resource group (for example `pathlit-rg`).
2. Create a **Computer Vision** resource and a **Speech** resource, both on the **Free F0** tier. Student subscriptions often allow only some regions;
   **East Asia** worked in development. The create form tells you if a region is blocked.
3. Open each resource, then *Keys and Endpoint*, and copy the endpoint, key and region into `.env`
   (names in the table above; never commit `.env`).
4. Run `pathlit setup`. It makes one real test call to each service and tells you what, if anything, is wrong.
5. Keys are secrets. If one is ever shown in a screenshot or log, regenerate it in the portal and update `.env`.

### 6. Responsible-AI and AI-901 view

| Topic | How Pathlit handles it |
|---|---|
| Computer vision (OCR) | Azure Read finds text and its position; the app never asks a model to guess pixel coordinates |
| Speech (synthesis) | neural voice, streaming, stoppable at any moment |
| Generative AI | a small model writes short text only; code verifies everything that matters (pass or fail, positions, actions) |
| Transparency | the pointer says what it will do; a red border and banner show whenever it controls the mouse |
| Privacy and security | screenshots are never saved; keys in `.env`; Groq gets text only; allow-listed actions only |
| Reliability | every Azure call has a fallback (Mirage, silence, lesson text) and the lesson never stops because a service failed |
| Inclusiveness | spoken and written instructions together; limits are documented under [Limitations](#limitations) |

---

## Quick start

**You need:** Windows 10 (2004+) or 11, one monitor, Python 3.11 or newer (built on 3.14), Blender 4.1, a free
[Groq](https://console.groq.com) API key, and an Azure account with **Computer Vision** and **Speech** resources (the free F0 tiers are enough).

```
# in the project folder
pathlit setup        # first time: creates .env, then checks your Azure keys
pathlit blender      # installs the Blender add-on; then close Blender completely and reopen it
pathlit doctor       # is everything ready?
pathlit              # start Pathlit
```

Type `pathlit` in the VS Code terminal (it activates the virtual environment for you), or `.\pathlit` in a plain PowerShell, or
double-click `pathlit.cmd`. The first run creates the Python environment and installs `requirements.txt` by itself.

Then: open Blender (Layout workspace, default scene), press **F8**, and do what the pointer shows.

### Manual install (if you prefer)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # fill in the values; never commit .env
.venv\Scripts\python scripts\install_addon.py --autoload
.venv\Scripts\python scripts\run.py
```

The Azure side is explained step by step in [Setting the Azure resources up](#5-setting-the-azure-resources-up). Get a free Groq key at
console.groq.com and put it in `.env` as `GROQ_API_KEY`.

## Configuration

`.env` (copy from `.env.example`; it is git-ignored):

| Key | Purpose |
|---|---|
| `AZURE_VISION_ENDPOINT`, `AZURE_VISION_KEY` | screen reading |
| `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | the spoken voice |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_MODEL_SMALL` | the teacher and the planner (`openai/gpt-oss-120b` and `-20b`) |
| `AZURE_SEARCH_*` | optional manual excerpts |
| `AZURE_OPENAI_*` | not used (see [Azure OpenAI](#4-azure-openai-not-used-and-why-groq-is-the-teacher)) |
| `DEBUG_SAVE_SCREENS` | keep `false`; screenshots are never written to disk otherwise |

`settings.yaml` (every value is commented in the file):

| Setting | Meaning |
|---|---|
| `hotkey`, `stop_key` | start / check key (`f8`; F9 is Blender's own) and the stop key (`esc`) |
| `mode` | `teach`, `show` or `do` at startup |
| `auto_advance`, `auto_window_title` | follow your clicks, but only when a window with this in its title has focus |
| `auto_settle_s`, `fast_settle_s`, `second_look_s`, `idle_hint_s` | timings of the auto-advance checks |
| `allowed_apps`, `action_delay_s`, `max_actions_per_task`, `mouse_move_s`, `mouse_abort_px` | Show me / Do it limits |
| `match_min`, `vision_max_edge`, `voice`, `provider`, `mirage_fallback` | matching threshold, image size sent to Azure, voice, model provider, local fallback |

## Using Pathlit

1. Start it. The control panel opens (top right of the screen; drag it by its header, collapse it with the chevron) and the terminal prints a status banner (lessons, Blender link, add-on version, teacher, auto-advance).
2. Press **F8** (or the main button) to start the next lesson. Pathlit announces it and points at the first target.
3. Do the step. The pointer fades when you click it, then glides to the next one. Wrong click or an open menu? Silence, not scolding.
4. Stalled for about 20 seconds? It explains the step once. **F8** at any time means "check me now"; after two misses you get a hint.
5. The panel lists every step: a filled check for done, a ringed dot for the current one, a numbered circle for the ones to come, and a thin bar for progress.

**In the panel:** type a task and press **Enter** (or the arrow button); click a suggestion ("a coffee mug", "a simple house", "a donut") to plan it at
once; **Up** recalls your last task and **Esc** clears the box; hover a step to see its full text; the status line at the bottom explains what Pathlit is doing.

Lessons: *Model a donut*, *Switch between Object and Edit mode*, *Move between workspaces*, *Your first look at Sculpt mode*,
*Add a light and a camera*, *Duplicate and delete objects*, *Read the Object properties*, *Find the render settings*. They are plain JSON in
`lessons/blender/`, validated on load (a bad file is rejected with the name of the step), and each step has a target (by text), a spoken
line, and a check.

## Typed tasks ("build a house")

Type a goal in the panel. Pathlit asks the model for a build plan, **checks it with code**, and queues it.

A plan is a list of parts, each with a shape and exact numbers:

```
Walls:  set Scale to X 2, Y 1.5, Z 1.25      set Location to X 0, Y 0, Z 1.25
Roof:   click Cone                           set Scale to X 2.5, Y 2.5, Z 0.75   set Location to X 0, Y 0, Z 3.25
Door:   click Cube                           set Scale to X 0.4, Y 0.06, Z 0.9   set Location to X 0, Y 1.56, Z 0.9
```

- The **code writes each instruction and each check from the numbers**, so the text you read, what Do it performs, and what is verified
  cannot disagree.
- The model is taught each shape's size and a stacking recipe (a roof's Location Z = top of the walls + its own half-height), and is told to
  use thin cubes, never planes, for doors and windows.
- A **geometry self-check** works out where every part ends up and flags parts that are below the ground, floating, mostly buried inside
  another part, a flat plane in mid-air, or hanging above a cone roof's sloping surface. If it finds a problem it shows the model its own
  geometry and asks for one correction.
- Menu items need their menu opened first; missing "Click Add / Click Mesh" steps are inserted automatically.
- Anything about scripts, Python or add-ons is dropped; non-Blender goals are refused politely. The plan assumes Blender's default scene.

The plans were rendered in a real Blender 4.1 during development to check them by eye (a roof buried in the walls, doors that were
invisible slivers, and a floating chimney were all found and fixed this way). Plans still vary from run to run, so treat the geometry warnings
shown in the panel as hints, not guarantees.

## Show me and Do it: the safety model

Cursor control is the most sensitive part of the project, so its rules are built into the code and tested (`tests/test_control.py`):

1. **You start it.** Nothing moves unless you chose Show me / Do it and pressed the start key.
2. **Esc always wins.** It stops movement and speech within a frame. Moving the real mouse more than 50 px during an action, or slamming it into a screen corner (`pyautogui`'s failsafe), also stops it.
3. **Allowed apps only.** The window in front must contain an entry from `allowed_apps` (default: Blender). If another window comes to the front, it stops.
4. **Warn before, check after.** A pointer and a countdown appear before every action; the step check runs after it; a failed check stops the task.
5. **No dangerous actions.** It will not click Save, Export, Delete, New, Open, Quit and similar unless the lesson step explicitly allows it. **It never types text or presses keys.**
6. **An allow-list for direct Blender actions:** add a primitive, switch mode, select an object, add a Subdivision / Bevel / Mirror modifier, set one named value, move / rotate / scale, set an exact location / rotation / scale, undo. Everything is validated in the app and **again inside the add-on**; nothing from a request is ever passed to `exec` or `eval`.
7. **A red border and banner** show whenever Pathlit is controlling your mouse.
8. **Everything is logged** to `logs/actions.csv`. At most 1 action per second and 40 per task.
9. **Text on the screen is data, never an instruction.** Only the lesson and your request decide what it does.
10. In **Teach me** mode the mouse-control library is not even imported.

Do it prefers a *direct* action inside Blender (for example "add a torus") over three menu clicks: it cannot miss a button. Show me uses
the cursor, except for steps a cursor cannot do (typing numbers), which it performs directly.

## Privacy

- Screenshots exist in memory for about a second and are **never saved** (unless you set `DEBUG_SAVE_SCREENS=true`).
- Pathlit looks at the screen **only after you interact**, only during a lesson, and only when a window with "Blender" in its title has focus.
- The screen is sent to Azure Vision for text reading (that is the one place an image leaves the computer). The model (Groq) gets **text only**: the step, a list of on-screen words and Blender's state. It never gets an image or coordinates.
- Keys live in `.env`, which is ignored by Git. `logs/` holds text and timings only and is ignored by Git.
- If anything fails (network, model, Blender link) the lesson carries on with its own text and screen-only checks.

## Command reference

| Command | What it does |
|---|---|
| `pathlit` | start Pathlit |
| `pathlit setup` | first-time setup: `.env`, then a test call to each Azure service |
| `pathlit doctor` | keys, Blender link, add-on version, is a copy already running |
| `pathlit stop` | close any running copy (only one can run at a time) |
| `pathlit blender` / `pathlit blender remove` | install / remove the Blender add-on |
| `pathlit shortcut` | put a Pathlit icon on your Desktop |
| `pathlit collect`, `label`, `eval`, `results` | the evaluation workflow |
| `pathlit test` / `pathlit test fast` | all tests / only the offline ones |
| `pathlit help` | the full list |

## Testing and evaluation

```
pathlit test fast      # about 270 offline tests, around 90 seconds
pathlit test           # also the live tests, which call Azure on real Blender screenshots (needs your keys)
```

Tests are named by requirement (`test_fr8_wrong_action_does_not_advance...`, `test_srs4_panel_...`). No test moves a real mouse; cursor control is tested with fakes,
and the add-on's actions were also verified in a real Blender 4.1.

The Phase 3 evaluation (pointing accuracy for Mirage vs Azure Vision vs a router, step-check accuracy, a user test) has its tools built and
validated, but **its data has not been collected yet**:

```
pathlit collect     # 50 planned scenes; saves only the Blender window, plus the add-on's state
pathlit label       # drag a box round each target text (hand-drawn, so truth never comes from a reader)
pathlit eval        # runs everything and rebuilds docs/results.md (which says NOT RUN for anything missing)
```

The protocol for the classmate user test is in [`docs/user_test_sheet.md`](docs/user_test_sheet.md) and a presentation script is in
[`docs/demo_script.md`](docs/demo_script.md).

## Project status

**Working:** the 8 lessons, auto-advance, the step checks, the pointer overlay, the spoken lines, the Blender add-on (state and allow-listed actions),
typed-task planning with the geometry self-check, Show me (confirmed to move and click on a real machine), Do it (built and tested with fakes and the
add-on's actions verified in a real Blender), the tray and the redesigned panel, the one-word launcher.

**Measured** (during development, on saved screenshots, real services):

| What | Result |
|---|---|
| Screen reading on 10 real Blender screens | Azure Vision found 94 to 128 text lines per screen; local Mirage found 11 to 30 and located only 2 of the 100 target-word checks (10 words x 10 screens), so Vision is the main reader |
| Pointer ready after a check starts | median ~0.9 s |
| First spoken word | median ~2.2 s (target 3 s) |
| Azure Vision upload | a 2048 px JPEG reads in about 0.9 s against about 1.7 s for the full-size image, with the same 16 of 16 test targets found |

**Not done yet:**
- The Phase 3 evaluation numbers and the user test (tools ready; see above).
- Do it end to end on a real run, the Esc / other-window / mouse-moved stops on a real run, and click accuracy at other display scalings.
- Undo (`ed.undo`) fails inside Blender's timer context; it is on the allow-list but not working, so there is no "undo everything" offer.
- A voice command to switch modes (needs speech-to-text).
- Azure AI Search (manual excerpts): the code, the index builder and the manual pages are written and tested with fakes only; no Search resource exists.

Every finding, decision, bug and open question is written down in [`docs/questions.md`](docs/questions.md) (65 numbered items).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `pathlit` is "not recognized" in PowerShell | PowerShell does not run programs from the current folder by name. Use the VS Code terminal (venv active), or type `.\pathlit` once; it then adds a short `pathlit` command to the venv. |
| "The Blender add-on is out of date" / HTTP 501 | Blender runs a **copy** of the add-on. Run `pathlit blender`, then close Blender completely and reopen it. Re-do this after any change under `blender_addon/`. |
| F9 does something in Blender | F9 is Blender's "Adjust Last Operation". The default start key is F8; change `hotkey` in `settings.yaml` if F8 clashes. |
| Two voices at once / a stuck pointer | Two copies of Pathlit are running. `pathlit stop`, then `pathlit`. A second copy now refuses to start. |
| Show me / Do it does nothing | Blender must be the window in front (Pathlit waits 10 s for you to click it). In Show me mode press the start key again as the OK. `logs/actions.csv` shows why a task stopped. |
| "The free model is busy" | Groq's free tier allows 8,000 tokens a minute for the planner model. Pathlit waits as long as Groq asks (up to 30 s) and retries once. |
| `.env` missing keys | `pathlit doctor` lists them (names only, never values). |
| The pointer lands on the wrong item | The same word can appear in several places. Pathlit prefers a standalone label, then the match nearest the previous target. Check `logs/session.csv` (`candidates` column). |
| The panel text looks different from the pictures | The panel prefers the Inter font and falls back to Segoe UI. Install Inter for the exact look. |

## Project layout

```
pathlit.cmd            launcher (creates the venv on first run)
settings.yaml          all tunable settings, commented
src/pathlit/
  cli.py main.py       the `pathlit` commands, and the application wiring
  controller.py        the cycle: capture, check, advance, point, speak, log; auto-advance triggers
  activity.py hotkeys.py   listen-only keyboard and mouse hooks
  capture.py           screenshots in memory, DPI handling
  perception/          azure_vision (primary), mirage_reader (local fallback), router, target_match
  lessons/             loader (pydantic), engine (the step loop), checks (code-decided pass/fail)
  brain/               teacher (Groq), planner + builder (typed tasks), vocabulary, docs_search, manual
  control/             actions (allow-list), guard (safety), mouse, executor (Show me / Do it)
  overlay/             the pointer and bubble (PyQt6), capture exclusion
  ui/                  control panel, labelling canvas
  voice.py             Azure Speech
  skillmap.py          SQLite skill map
  evaluation.py capture_plan.py   Phase 3 evaluation logic
blender_addon/         the Blender add-on (state, allow-listed actions) and its autoload script
lessons/blender/       the 8 lessons (JSON)
scripts/               run, install the add-on, spikes, evaluation, data collection, labelling, make_readme_images
tests/                 about 270 offline tests plus live tests
docs/                  questions.md, results.md, do_mode.md, demo script, user-test sheet, images/ (README pictures)
```

## Design decisions

- **The model writes words; code decides.** Step advancement depends only on code checks, and pointer positions only on the screen reader.
- **Azure Vision first, Mirage as the fallback.** The first plan was local-first, but on Blender screens Mirage found almost none of the UI text, so the order was reversed. Mirage keeps the app usable offline.
- **Groq instead of Azure OpenAI.** No Azure OpenAI model could be deployed on the student subscription in its allowed regions. The teacher is Groq (text only) behind an interface that also supports "none", where lessons use their own text.
- **One click per step.** Menu steps are split so every check is clean and the pointer can move between clicks.
- **Checks that cannot pass early.** A first-step screen check must not already be true on the untouched layout (this caught a real bug in lesson 5, where "Light" is also an object in the Outliner).
- **Nearest-to-the-last-target matching** and **standalone-label preference** fix the "same word in two places" problem (the Object menu vs the word in "Object Mode"; the Add menu's Camera vs the Camera object in the Outliner).
- **The Blender add-on re-validates everything.** The app checks every action, and the add-on checks it again, because it is the part that changes the scene.
- **A quiet, neutral panel.** The control panel uses a zinc palette, 1 px borders and one white primary button, so the colour on screen belongs to Blender and to the pointer.

## Limitations

- Windows only, one monitor, English only, Blender 4.1 menus (the lessons and the label lists are for 4.1).
- Pointing needs the target to have **text**; icons (like the Modifiers wrench) are described but not pointed at.
- Typed-task plans vary between runs and depend on the model's arithmetic. They assume the default scene, and cones are round.
- The free tiers have limits: Azure Vision allows 20 calls a minute, Groq 8,000 tokens a minute on the planner model.
- A single-user prototype. No accounts, no storage of anything about the learner.

## Credits and licences

- Blender manual excerpts (an optional index; the manual pages are downloaded locally and are **not** in this repository): Blender Documentation Team, CC BY-SA 4.0.
- The Blender screenshot behind the demo pictures shows Blender 4.1 (GPL), used only to illustrate the app.
- [Mirage](https://cactuscompute.com) (local text reader): Cactus Compute, Apache 2.0. Azure Vision, Speech and Search: Microsoft. Teacher and planner model: Groq (`openai/gpt-oss`).
- PyQt6, pynput, pyautogui, mss, rapidfuzz, pydantic, pandas, matplotlib and the other packages in `requirements.txt` keep their own licences.
- **Project licence: not chosen yet.** Until a `LICENSE` file is added, all rights are reserved by the author.
