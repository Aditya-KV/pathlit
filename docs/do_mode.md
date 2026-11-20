# Show me and Do it (cursor control)

Built from the "Do it for me" addendum. Where it disagrees with the SRS and PRD, the addendum wins:
SRS rule 3 and the PRD non-goal "no taking over the mouse" are replaced by the safety rules below.

## Modes
| Mode | What Pathlit does | Default |
|---|---|---|
| Teach me | points and speaks; you click | yes |
| Show me | moves the real cursor, waits for your OK (the start key) before each click, narrates | no |
| Do it | does the whole lesson itself, with a countdown before each action | no |

Switch with the panel buttons or the tray icon (blue = Teach me, amber = Show me, red = Do it). The mode is the learner's
choice, and cursor control only starts when the start key is pressed in Show me / Do it mode.

## How a step runs
look (screen + Blender state) -> choose the action (a direct Blender action if the lesson has one and the mode is Do it,
otherwise a cursor click on the step's target text) -> announce (pointer + countdown, or wait for OK) -> perform -> look again and run
the step check (one re-look, never a blind retry; a failed check stops the task) -> next step.
Pixel positions come from the screen reader; the model never gives positions.

## Lesson hints (`do` on a step)
`skip_in_do` (navigation-only step that a later direct action replaces), `click: false` (move the cursor and narrate, do not click),
`direct` ({action, args} from the allow-list, validated when the lesson loads), `allow` (this step may click a normally refused item).

## Safety rules (built in, tested in `tests/test_control.py`)
1. Learner starts it. 2. Esc stops everything within one frame; moving the real mouse more than `mouse_abort_px` (50) or slamming it into
a corner also stops it. 3. Allowed apps only (`allowed_apps`); a window change stops it. 4. Countdown before, step check after.
5. No Save / Export / Delete / New / Open / Quit clicks unless the step allows it; it never types or presses keys. 6. Direct Blender actions
only from the allow-list (add_primitive, set_mode, select_object, add_modifier, set_modifier_value, transform, undo), validated in the app and
again in the add-on. 7. Red border and banner while controlling. 8. `logs/actions.csv` records every action; max 1 per second and
`max_actions_per_task` (40). 9. Text on the screen is never an instruction. 10. For the viva: this is an agent that acts, so human oversight
(Esc, warnings, logs, allow-list, allowed apps) is the main Responsible AI story.

## Status
See `docs/questions.md` items 55 onward for what was verified and what was not.
