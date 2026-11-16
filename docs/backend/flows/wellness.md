# Flow: RPE, soreness, sleep and recovery exercises

**Status: built** (`backend/wellness/`, [API](../api/wellness.md)), except the deferred recovery level and suggested times. Rules: [wellness](../logic/wellness.md). The recovery level and suggested times are **deferred** to the owner's sports-expert partner.

Models: [SessionParticipant](../models/bookings.md), [SorenessLog, SleepLog, Exercise, ExerciseBodyArea, ExerciseAssignment, UserAchievement](../models/wellness.md), [Group](../models/teams.md).

| Step | What happens | Rules |
|---|---|---|
| 1. Session ends | Checked-in participants get one RPE reminder | [NOTE-31](../logic/notifications.md#the-scheduler) |
| 2. RPE form (under two minutes) | Effort, minutes, sore areas; unlocks the video | [WEL-1 to WEL-5](../logic/wellness.md#rpe-after-a-session) |
| 3. Morning and evening check-ins | Sore areas and levels | [WEL-10 to WEL-12](../logic/wellness.md#soreness-check-ins) |
| 4. Sleep | Typed in, or imported from Apple Health / Health Connect by the phone | [WEL-20 to WEL-23](../logic/wellness.md#sleep) |
| 5. Exercise suggestions | Computed from soreness; the player picks some | [WEL-30 to WEL-33](../logic/wellness.md#exercise-suggestions) |
| 6. Coach-sent exercises | To a player or a whole team | [WEL-40 to WEL-44](../logic/wellness.md#coach-assignments) |
| 7. Achievements | First exercise, 7-day streak | [WEL-50, WEL-51](../logic/wellness.md#achievements) |

```
SorenessLog(quads, 6) ─> Exercise ⋈ ExerciseBodyArea(quads), 6 in [min,max]
                              └─> picked: ExerciseAssignment ─ completed_at ─> UserAchievement
```

What is read back: training load `rpe × rpe_minutes` per session ([RPT-8](../logic/owner-reports.md)), soreness per area over time, sleep duration, open exercises. A coach sees these for their players only ([TEAM-40](../logic/teams-and-coaching.md#what-a-coach-can-see-about-their-players)).
