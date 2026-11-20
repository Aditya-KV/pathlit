# Demo script (about 6 minutes)

## Before you start (5 minutes earlier)
- [ ] Only one copy of Pathlit will run. Close any old terminal first.
- [ ] Blender 4.1 open, **Layout** workspace, default scene, window not covered. Add-on on (the banner will say "Blender link: connected").
- [ ] `.venv\Scripts\python scripts\run.py`, wait for the banner: lessons loaded 8, Teacher model Groq, Auto-advance ON.
- [ ] Speakers on, volume checked. Network on. Panel visible at the right of the screen.
- [ ] `docs/results.md` open in a second window for the numbers.
- [ ] Back-up plan if the network fails: the lessons still run on their own text (say so, that is a feature).

## 1. The problem (30 s)
"Beginners quit Blender because the screen is crowded and tutorials do not know where you are stuck. Chat assistants cannot see
your screen. Pathlit sits next to your cursor, remembers what you know, and checks that each step really worked."

## 2. The lesson (2 min): "Model a donut"
1. Press **F8**. It says the lesson name and the first step; the pointer flies to **Add**. *(Point out: the position comes from reading
   the screen, not from the model.)*
2. Click Add. The pointer glides to **Mesh**, then **Torus** after you click Mesh. *(Auto-advance: no key presses needed.)*
3. Click Torus. The donut appears. *(The Blender add-on confirms the object, not just the picture.)*
4. Open the **Object** menu and click **Shade Smooth**. Then the wrench icon, **Add Modifier**, **Generate**, **Subdivision Surface**.
5. At the end: "Lesson complete" and it suggests the next lesson. The panel shows every step ticked.

## 3. It checks, it does not just talk (45 s)
Start the lesson again, or use lesson 2. At a step, **click the wrong thing** (for example open Edit instead of Add):
Pathlit stays quiet while you are mid-step; wait about 20 s, or press F8, and it explains the same step differently. Press F8 a
second time and it shows a hint. *(Step advancement is decided by code checks, never by the language model.)*

## 4. Your own task (1 min)
In the panel type **"add a monkey head and make it smooth"**, click **Plan steps**. Read the plan aloud (Add, Mesh, Monkey, Object,
Shade Smooth). Press F8 and follow it. Say: "The model writes the plan; the code checks it: only real Blender labels, no code, missing
menu steps added automatically. A non-Blender goal like baking a cake is refused."

## 5. The numbers (1 min) , open `docs/results.md`
- Pointing accuracy for Mirage (on-device), Azure Vision, and the router; why the app uses Azure Vision first.
- Step-check accuracy, and the false passes.
- Time to first spoken word versus the 3 s target; cost per lesson ($0 on the free tiers).
- The user test, and say honestly that it is a small sample.

## 6. Responsible AI (45 s)
- **Teach me only points and speaks.** Show me and Do it move the mouse, but only when you choose them: Esc stops at once, only Blender is allowed, a countdown comes before every action, a check after, an allow-list for Blender actions, a red border while it is active, every action logged. Nothing types.
- Screenshots stay on the laptop and are never saved; the model gets text only; it only looks after you interact and only when Blender is focused.
- Transparency: every spoken line comes from the lesson or from a logged model reply (`logs/prompts.jsonl`).
- Reliability: no network, no add-on, no model: it degrades to lesson text and screen-only checks.

## Likely questions
- **Why not Azure OpenAI?** The student subscription could not deploy a model in its allowed regions; the teacher is Groq behind the same interface. (`docs/questions.md` #16-18.)
- **Why not only the on-device model?** Mirage found almost none of Blender's UI text in the first test; the numbers are in `docs/results.md`.
- **What if the menu is different on another Blender version?** The lessons are for 4.1; the manual excerpts are the 4.1 manual; labels are checked on the real screen.
- **Does it record me?** No. Screenshots live in memory for about a second; logs hold text and timings only.
