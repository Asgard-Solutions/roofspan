# RoofSpan Field — Follow-ups, My Day, photos and upgrade: manual device acceptance checklist

Nobody has run this on a real phone, emulator or simulator yet. No Android emulator or iOS simulator was available.
**Before you start:** install the release-candidate Office build (0.5.0) first and let it finish upgrading. The database must be at
migration `c7e2a9b4d1f3`. Then install the Field build (1.1.0) from the same release candidate. Field 1.1.0 refuses to sync
with an older Office and Office 0.5.0 refuses Field 1.0.0 (section G).

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

## E. Won / Lost closes follow-ups
20. Give a test lead two open follow-ups, one completed follow-up and one you cancelled yourself.
    - In **Office**, set the lead to **Won**.
    - **Expect (Field, after a refresh):** both open follow-ups are gone from Follow-ups and from My Day.
    - **Expect:** "+ Follow-up" is hidden and you see "Lead is won. Change the status to reopen it…".
    - **Expect (Office contact history):** the two show as cancelled with the reason "Lead marked Won". The completed one and your own cancellation are unchanged.
21. Same setup, but in **Field** edit the lead and set the status to **Lost** while **offline**.
    - **Expect:** the open follow-ups disappear on the phone straight away.
    - Close and reopen Field while still offline. **Expect:** they stay gone.
    - Go online. **Expect (Office):** they're cancelled with "Lead marked Lost". Nothing was deleted.
22. Field is offline and has **Done** waiting on a follow-up. Meanwhile, Office marks the lead Won.
    - Bring Field online.
    - **Expect:** a "Changed in Office" card offering only **Keep Office version**. The follow-up stays cancelled ("Lead marked Won") and is never reopened.
23. Accept a proposal for a lead that has an open follow-up.
    - **Expect:** the lead becomes Won and the follow-up is cancelled with "Lead marked Won".
    - **Expect:** the new job, its dates and its crew are unchanged.
    - Then set the lead to Lost. **Expect:** the job is still unchanged.
24. Reopen a Won or Lost lead by setting it to Contacted.
    - **Expect:** the old cancelled follow-ups stay cancelled.
    - **Expect:** "+ Follow-up" is back, and a new follow-up shows up as open in Office, Field and My Day.
25. Field is offline, a follow-up was scheduled offline, and Office marks the lead Lost before the phone syncs.
    - **Expect after sync:** the follow-up exists in Office but is already cancelled ("Lead marked Lost"), so it never shows as overdue.
26. Office Home and Field My Day counts: after steps 20–25, the lead isn't counted under Follow-ups due or No follow-up while it's Won or Lost.
    - **Expect:** its next step is the stage guidance (for example "Schedule the job."), the same in both apps.

## F. Photos: capture, upload, retrieval, Office ↔ Field
Use a lead or job created for this test. The older test photos that show "not found" in preview are damaged test data and are left as they are.
27. Online: on a lead, tap **Take photo**, take a picture, add a note.
    - **Expect:** the photo appears on the lead in Field within a few seconds, then in Office on the same lead (Photos) with the same note.
28. Online: on a job, tap **Library** and pick an existing picture.
    - **Expect:** it uploads and shows in Office on the job. Open it full size in Office and in Field.
29. Offline (airplane mode): take two photos on a lead.
    - **Expect:** they show on the phone straight away as waiting to upload; nothing is lost when you close and reopen the app.
    - Go back online. **Expect:** both upload once (no duplicates) and appear in Office.
30. Office uploads a photo to a lead (Receiving / Photos). **Expect:** Field shows it on that lead after refresh.
31. Close Field, reopen it, open the lead again. **Expect:** all photos from steps 27–30 still load (none show "Photo file unavailable").
32. Installed Office: after steps 27–31, restart the computer and open the same lead in Office. **Expect:** every photo still loads (installed Office keeps photos on its own disk).

## G. Office / Field versions and upgrading (RoofSpan Office 0.5.0, RoofSpan Field 1.1.0)
Supported order: upgrade **Office first**, then Field on every phone. Sync any pending work before upgrading where possible; it is never deleted either way.
33. Field 1.1.0 with Office 0.5.0. **Expect:** connects and syncs normally. Check the version in Android Settings → Apps → RoofSpan Field (or iPhone Settings / TestFlight): 1.1.0.
34. Field 1.1.0 with an Office still on 0.4.8.
    - **Expect:** "RoofSpan Office needs an update" with the Office version shown and **Try Again**. Nothing syncs.
    - Upgrade Office to 0.5.0, tap **Try Again**. **Expect:** Field connects and any waiting changes sync.
35. Field 1.0.0 with Office 0.5.0 (an un-updated phone).
    - **Expect:** Field 1.0.0 can't load or send data (it shows its usual error). Office rejects every request until the phone is updated, so nothing partial is saved.
36. Upgrade Field with pending offline changes:
    - On Field 1.0.0, go offline, change a lead's status (for example to "Interested") and add a visit and a photo.
    - Install Field 1.1.0 over it (don't uninstall). **Expect:** still paired and signed in, the changes are still waiting.
    - Go online. **Expect:** everything syncs once; the "Interested" lead shows as **Qualified** in Office and Field.
37. Android: the 1.1.0 test build installs over the existing app as an update (no uninstall prompt). iOS: the TestFlight/ad-hoc 1.1.0 build replaces the old one.

Note: proposal email and ABC Supply are still MOCKED (simulated); neither is part of this checklist.
