# RoofSpan Field — Follow-ups & My Day: manual device acceptance checklist

Nobody has run this on a real phone, emulator or simulator yet. No Android emulator or iOS simulator was available.
Do it on one Android phone and one iPhone, signed in as a salesperson. Keep RoofSpan Office open in a browser as an owner.
Use a test lead assigned to that salesperson. Turn on Airplane mode for the offline steps.

Mark each step **Pass** or **Fail** and note what you saw.

## A. Online, Office ↔ Field
1. In Office, open the lead and add a follow-up (Call, tomorrow 9 AM, "TEST A").
   - In Field, pull down on Leads, then open the lead.
   - **Expect:** "TEST A" shows under Follow-ups with tomorrow's date. Next step reads "Call: TEST A".
2. In Field, tap **+ Follow-up**, choose Text → Today → 5 PM, add the note "TEST B", and tap Save.
   - In Office, refresh the lead.
   - **Expect:** "TEST B" is listed. The Home "Follow-ups due" card shows it as due today.
3. In Field, tap **Done** on "TEST B".
   - **Expect:** Office shows it in Contact history, and "TEST A" is still open (each follow-up is separate).
4. In Office, reschedule "TEST A" to next week.
   - **Expect:** Field (after a refresh) shows the new date.
5. In Office, cancel "TEST A" and wait 5 seconds.
   - **Expect:** Field (after a refresh) no longer lists it as open, and it doesn't appear in My Day.
6. In Field, record a door visit "Callback requested".
   - **Expect:** Field asks you to schedule a follow-up.
   - **Expect:** In Office, Contact history shows that door visit exactly once.
7. In Field, tap **Book inspection** (Tomorrow, 12 PM).
   - **Expect:** Office shows "Booked · <date>", and My Day → Inspections lists it.
   - In Office, tap **Record results** and save.
   - **Expect:** Field no longer shows it as booked.
8. Check the next step.
   - **Expect:** Field Lead Detail, Field Leads list, the Office Leads list and the Office Lead Detail banner all show the same wording.

## B. Offline
9. Turn on Airplane mode. Schedule a follow-up "TEST C" (Today, 3 PM).
   - **Expect:** It shows "waiting to sync", My Day → Due today shows it, and nothing crashes.
10. Still offline, tap **Done** on "TEST C".
    - **Expect:** It leaves the open list and My Day.
11. Still offline, close Field completely and reopen it.
    - **Expect:** My Day shows "as of last sync", and "TEST C" is still done, not back to open.
    - **Expect:** More → Sync shows the changes waiting.
12. Turn Airplane mode off.
    - **Expect:** The waiting changes sync on their own within about 15 seconds, or when you tap Sync now.
    - **Expect:** In Office, "TEST C" exists **once** and is marked done.
13. Interrupt a sync:
    - Go offline and schedule "TEST D".
    - Go online, then switch Airplane mode back on within a second.
    - Turn Airplane mode off again.
    - **Expect:** Office has exactly **one** "TEST D".
14. Conflict, case 1:
    - With Field offline, tap Done on a follow-up.
    - Meanwhile in Office, reschedule that same follow-up.
    - Bring Field online.
    - **Expect:** Field shows a red "Changed in Office while you were offline" card with **Keep Office version** and **Apply mine**.
    - Choosing either one clears the card. More → Sync shows no conflict left.
15. Conflict, case 2:
    - Same as step 14, but **cancel** the follow-up in Office instead of rescheduling it.
    - **Expect:** Only **Keep Office version** is offered.
    - **Expect:** The follow-up stays cancelled and never reappears.

## C. Reassignment
16. In Office, reassign the lead to a different salesperson. On the first phone, pull down on Leads and on My Day.
    - **Expect:** The lead and its follow-ups disappear.
    - **Expect:** Opening the lead from a link or the back stack shows "Lead not available".

## D. Dates and times
17. Set the phone to a different time zone than the Office computer, for example phone Pacific and Office Central.
    - Add a follow-up for 11:30 PM tonight in Field.
    - **Expect:** Each device shows the same moment in its own local time.
    - **Expect:** "Today" or "Overdue" follows each device's own clock.
18. Around midnight, or by moving the phone's clock forward past midnight:
    - **Expect:** a follow-up that was due "Today" yesterday shows as **Overdue**, even while offline.
19. Optional, on a daylight saving change day: a follow-up at 11:30 PM still shows "Today". 12:30 AM the next day shows "Upcoming".

Note: proposal email and ABC Supply are still MOCKED (simulated); neither is part of this checklist.
