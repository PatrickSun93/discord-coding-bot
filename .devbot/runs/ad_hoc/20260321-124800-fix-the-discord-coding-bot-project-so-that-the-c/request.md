Fix the discord-coding-bot project so that the coding CLI can work in parallel on different projects. Currently only 1 CLI is working on one project at a time. This is the highest priority task.

Investigate the current architecture and implementation to understand:
1. How projects are currently locked/assigned to a single CLI
2. Why parallel processing isn't working across different projects
3. What needs to change to allow multiple CLIs to work on different projects simultaneously

Then implement the fix to enable true parallel processing of different projects.