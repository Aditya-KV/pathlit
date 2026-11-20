# User test protocol: Pathlit vs a YouTube tutorial

**Question:** do people finish the same Blender lesson faster, or more of them finish, with Pathlit than with a video tutorial?

## Who and how many
8 to 10 classmates who have **never used Blender** (or only opened it once). Split them evenly and at random into two groups:
**pathlit** and **youtube**. Note a participant number only (P01, P02...). Collect no names or other personal data.

## The task (identical for everyone): "Model a donut"
Starting point: Blender 4.1, default scene, Layout workspace. The task is finished when **all of these are true** (the observer checks):
1. a Torus object exists (not the cube),
2. it is smooth shaded (Object > Shade Smooth),
3. it has a Subdivision Surface modifier.

Time limit: 20 minutes. If they are not done, they are marked "not finished" with the time at which they stopped.

## Setup
| | Pathlit group | YouTube group |
|---|---|---|
| Help | Pathlit running; the observer presses F8 once to start, then says nothing about how to use it | A beginner "Blender donut" video chosen beforehand and **the same for everyone** (write its title here: ________) |
| Allowed | speaking to the app is not needed; asking the observer for help is not allowed | pausing, rewinding, replaying |
| Not allowed | looking up other tutorials | looking up other tutorials |

Give the same 1-minute introduction to both groups ("this is Blender; make the donut"). Do not explain menus.

## What the observer records for each person
- **Finished** (1 or 0), checked against the three conditions above.
- **Minutes** from "go" to finished (or to the time limit).
- **Clarity**: ask afterwards, "How clear were the instructions, from 1 (very confusing) to 5 (very clear)?"
- **Notes**: where they got stuck, anything the app did that surprised them (one line).

## Recording sheet
Save as `docs/user_test_results.csv` (this exact header; `scripts/make_results.py` reads it):

```
participant,group,finished,minutes,clarity,notes
P01,pathlit,1,9.5,4,"pointer was easy to follow"
P02,youtube,0,20,2,"kept pausing, lost the menu"
```

## After the test
Run `python scripts/make_results.py`. Section 4 of `docs/results.md` compares the groups. With 8 to 10 people the result is
indicative only; say so when presenting it, and report it honestly if the YouTube group did as well or better.

## Ethics and safety
Tell participants: it is a test of the tool, not of them; they can stop at any time; nothing personal is recorded. Pathlit takes screenshots
only while Blender is focused during their lesson and does not store them.
