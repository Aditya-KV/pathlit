# Pathlit: rules for the implementing agent

1. Build one phase at a time (SRS Section 13). After each phase stop, report what works and what you measured, and wait for the owner.
2. Never guess an API. If a library call or Mirage's output format is unknown, write a spike script, run it, report the real output.
3. In Teach me mode (the default) the app only points and speaks. ONLY in Show me and Do it mode, started by the learner, may it move the mouse and click, and only under the safety rules in docs/do_mode.md (Esc stops it, allowed apps only, countdown, checks, allow-list, no typing, log). pynput is still used only to listen; mouse control uses pyautogui, loaded only when needed.
4. Target positions come from the screen reader (Mirage or Azure Vision), never from the language model.
5. Screenshots stay on the laptop. Send Azure only text, except the Azure Vision fallback (FR-9). Never save a screenshot unless DEBUG_SAVE_SCREENS=true.
6. Keys live in .env, never in code or Git.
7. Ask before adding any dependency not in SRS Section 4.
8. Every requirement gets a test or measurement script; put the requirement number in the test name (e.g. test_fr7_step_check_passes).
9. Keep code simple: type hints, small modules, plain logging, a timing log for each step.
10. If a requirement is unclear, write the question in docs/questions.md and continue with the safest choice.
