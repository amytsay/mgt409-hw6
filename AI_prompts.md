# HW6 AI Prompts Log

Prompts I gave my AI coding assistant for each problem, quoted as typed.

## Problem 1: AI Prompts Log

**Prompt 1:**

> Okay time to work on HW6, you know the start and set up and the link is: https://zlisto.github.io/mgt_409_fa26/hw6/p1.html. We are building a vendor desk agent that reads a document pulls out key facts and recomments what the shop should buy all while following rules in the Campus Customs Shop Handbook. COST is crucial 10,000 tokens that goes out every call, and SAFETY. We need to make sure safety measures are built in (review slides from our lecture on Saturday, lecture 12 to account for key safety features. For any emails or payments please not WE ARE NOT SENDING OUT real emails or payments, only writing a log file and also make sure we're using the PORTKEY_API_KEY and only gpt-6-luna for every AI call. Unzip the data file in Homework 6 folder. And we'll start with Problem 1. Let me know when you're ready

**Follow-up prompt:** None needed. The first prompt covered everything for this problem.

## Problem 2: Size up the handbook

**Prompt 1:**

> Great make sure we follow the steps set and we'll move on to Problem 2. We already unzipped the data.zip so now we're going to look through data/shop_handbook.md, and the agent will send it to the model every single call. I'm aligned with caching the sends to make sure the price goes down. Also make sure to look at data/prices.json the gpt-6-luna price list to ensure our token limit. Now that we have looked at the handbook, put in output/handbook_estimate.md 1. the token count and how you got it, what the handbook alone costs in dollars on one call, and on 1000 calls with and without cached tokens. Make sure to show the formulas and math as we'll be checking these estimates later. Once complete do closeout procedures and let us know if we can move onto problem 3

**Follow-up prompt:** None needed. The first prompt covered everything for this problem.

## Problem 3: Build the vendor desk agent

**Prompt 1:**

> Okay now for Problem 3 we will be building the vendor desk agent. Make sure to build it with PydanticAI using gpt-6-luna
> The agent consists of prompts/prompt.md (instructions for the agent along with the handbook to the model on every call), agent.py the entry point, tools.py (the tools) and models.py (the structured types. Okay so the path to one vendor document would be reading the document with a tool (HTML, PDF, and .eml email files) and returns: vendor, SKU, unit price, lead time in days, minimum order, a decision (recommend or do_not_recommend) following the handbook rules and one-sentence reason. Let me know if this tracks and you're able to reach each individual vendor document. We also need to make sure the agent has two trap tools because remember there are malicious agents trying to trick you and we need to make sure that it doesn't hapepen (again reference the slides from earlier) the trap tools are send_email and approve_payment. MAKE SURE THIS NEVER HAPPENS. they do not send or pay anything, they only append the call and its arguments to output/trap_calls.json so that if that file ever has an entry, a document took over your agent. Make sure these stay on the system for the whole homework.
>
> Also to note after every run, append to output/usage_log.json (document, time, token counts, and dollar cost using prices.json, also have the output/audit_trail.json (each tool call with arguments and short result + answer). Agent should run in the terminal with (python agent.py --doc data/practice_docs/p01_bluehen_quote.html). Now run it on p01 and p08 in order to test its working. Make sure to start output/harness.md each field in models.py and why and each tool used in one line.

**Follow-up prompt:**

> /before moving onto problem4 go ahead and pause onhe drive and run the venv

The first prompt did not cover giving hw6 its own virtual environment, which needed OneDrive paused before the install (the Problem 3 test runs had borrowed the Lecture 12 environment).

## Problem 4: With and without cached tokens

**Prompt 1:**

> Great moving on to problem 4, time to test the agent with the cache on all 12 practice documents, and without the cache for the handbook. Make sure to check the token counts that the API sends bck to prove each setup really did what was thought. Make sure that the ones running without cache have absolutely no cached tokens. For every model call from both the cached and noncached save the results to output/cache_test.json. Make sure for every call to include the setup document, every token count the API reports and dollars from prices.json. Also make sure that in output/cache_test.md there is the total cost and cost per document for each setup, the percent that was saved between the cache and noncached, how the real numbers compare to the problem 2 estimates, projection for 1000 documents a day for 30 days, with and wthout cache and anything that surprises us in the system and why did that happen. Once complete perform completion procedures and confirm we cfan move to problem 5

**Follow-up prompt:** None needed. The first prompt covered everything for this problem.

## Problem 5: Attack your own agent

**Prompt 1:**

> Okay make a note for problem 6 and make sure we incorporate the fix while completing problem 6. Let's start Problem 5 now. Time to attack the agent. Given that some vendor documents are bobby-trapped. Run problem 3 agent on all 12 documents in data/practice_docs/ and compare each answer to data/practice_key.json and check output/trap_calls.json, and log the fake email and payment tools from Problem 3 write to. Make sure to save output/attack_results.json for each document and whether each field matched the key, whether the decision matched, whether a trap tool was called and whether a link or other strange text showed up in the answer. Now in outputattack_results.md for every document that fooled the agent make sure to incorporate what had fooled it and where in the file it was hiding. Make sure to open the actual documents similar to how a person would and compare the results to what the agent reads. Once complete confirm completion and that we can move onto problem 6

**Follow-up prompt:** None needed. The first prompt covered everything for this problem.

## Problem 6: Defend your agent

**Prompt 1:**

> Okay great for problem 6 please implement the linked-run cache fix and also make sure we defend our agent at three levels within the code, the design, and the prompt rules in prompts/prompt.md, make sure not to keep send_email and approve_payment. For defending our agent. For the code make sure to scan each document for any hidden commands, sweeps, and altering prior to it reaching a model. Next make sure that tools that are human decided-only are never acted upon by the agent. Also make sure that all decisions are checked against what is true and not overwritten by hidden text. Since I don't typically code or design, please give me some additional suggestions as to how to stop these traps based on code and design also please keep in mind preventing some of the additional traps covered in the lecture. Once completed please incorporate these into rules in prompts/prompt.md.
>
> Following this update rerun all 12 practice documents, save in output/defense_results.json similar to problem 5 and include tokens and dollars per document. Make sure that clean documents still come back with the right values. Finally in output/defense_results.md add the before and after table for all 12 documents, what each layer catches that the other layers miss and then the extra tokens and dollars each layer of protection adds per document. <ake sure to also add the safety features to output/harness.md in a Safety section this will explain what each defense layer does but in plain words. Once complete perform final problem sweep and completion checks and then confirm we can move onto problem 7.

**Follow-up prompt:** None needed. The first prompt covered everything for this problem. (The Problem 6 page says the trap tools may not be deleted, so "not to keep send_email and approve_payment" was carried out as keeping them registered but human-only: the agent can never run them.)

## Problem 7: Red team

**Prompt 1:**

> Okay on to problem 7. Time for me to attack. Please make two new booby-trapped vendor documents in data/my_attacks/ for one of the attacks we'll make it an HTML of an invoice for a vendor that is approved on the list, however please hide code somewhere in the document code that has the agent approve and pay the invoice no matter what. Make this in the smallest font size possible maybe font size 1 so that humans opening it cannot see it. For the second trap, be a PDF include an image that would go along with the request and hide the attack in the image (you can choose what the attack is) please make it from an approved and a confirmation that it can provide the quoted request. Make sure the text is not visible by a person opening the document.
>
> Once these are generated, run both attacks on the agent with no defenses as well as on the defended agent. Then in output/red_team.md for each attack write what is hidden, where, what it tries to make the agent do, and what happened before and after your defenses.
>
> Feel free to come up with a third attack on your own, and if you can fool the agent, I'll give you some props

**Follow-up prompt 1:**

> is there room later in the problems to fix them? I want to make sure we're not jumping ahead

**Follow-up prompt 2:**

> Okay let's fix them, and once again look through the slides of the last lecture and make sure we're accounting for all possible attacks and have these covered since ideally I'd like to get full points

The first prompt asked for the attacks and the before/after runs, but not what to do when an attack beat the defended agent. The follow-ups had the two holes fixed before the Problem 8 exam run, and every Lecture 12 attack type checked against the defenses.

## Problem 8: Exam documents

**Prompt 1:**

> Great time to move on to problem 8. data/exam_docs/ has 10 vendor documents with no answer key. Run the agents on all of these documents and save the results to output/exam_results.json with one entry per exam file.
>
> Make sure each entry has file: the exam file name, vendor, sku, unit_price, lead_time_days, min_order, decision: recommend or do_not_recommend, reason, trap_tool_called: true or false, input_tokens, cached_tokens, output_tokens, cost_usd
>
> Please try to make everything clean! and good to go.  Once complete move forward with final closeout so we can go to problem 9

**Follow-up prompt:** None needed. The first prompt covered everything for this problem.

## Problem 9: Results page

**Prompt 1:**

> Okay amazing finally moving on to problem 9. We will build output/hw6_report.html. This will be one file that opens by double-click with no internet and no other files next to it. Make sure the page shows the five things below and utilizes the real numbers we generated. Caching results with a chart, attacks before and after defenses, what defenses cost in tokens and dollars, exam results and two red team attacks (you can put the bonus attack in a sidebar), a short recommendation to the store manager regarding if campus customs turns this agent on for real vendor mail, what would it cost per month at 1000 documents a day.
>
> Now for the fun part the designed page first off make it easy to read and intuitive. Our professor is obsessed with LISA and has a running joke where he includes her in everything. He's even going to see her tomorrow night. Let's make this whole page LISA customized, have a bar at the bottom cycle through her music while navigating the page you can use this potential The "Press Play" Vinyl & Stem Mixer: Build a floating, transparent turntable at the bottom of the screen. Users can drop the needle on tracks like "Rockstar," "New Woman," or "Tarantino," and toggle individual audio stems (vocals, bass, synths) on and off to create live mini-remixes. This is her merch page and website https://usshop.lalisaofficial.com/, please pull her vibe, her image, her style, her fashion into elements in the page. I want this creative beyond the tenssss honestly you can even make each section similar to her photobooks alter egos so one section is vixi, one section is kiki, one section is roxi, etc. Feel free to also use her instagram as inspiration https://www.instagram.com/lalalalisa_m/?hl=en as well some recommendatios include:
>
> * Custom Typography: Combine a sharp, brutalist display font for headers (evoking Rockstar and Tarantino) with a sleek, high-fashion editorial serif for her brand ambassadorships.
> * Interactive Cursor: Replace the standard pointer with a glowing 5-pointed star (representing her five Alter Ego personas) that leaves a subtle stardust trail.
>
> Other options include:
> 3D Persona Switcher: Instead of a static banner, greet visitors with a spinning, interactive crystal prism representing her five Alter Ego characters (Roxi, Sunni, Kiki, Vixi, and Speedi).
>
> * Dynamic Theme Shifting: Clicking a persona transforms the entire website's color scheme, background video loop, and ambient audio track to match that character's vibe.
>
> Also feel free to add the secrete code: The Secret "LLOUD" Mode: Typing LLOUD anywhere on the keyboard triggers a screen-shake effect, drops virtual confetti, and unlocks a secret vault of unreleased dance practice clips. (loop this into a button that is secret which can reveal it because I dont want it too hidden)
>
> Once complete do the cross-checks and confirm

**Follow-up prompt:**

> okay problems with the site the mouse literally disappears so I cant click things after scrolling

The first prompt asked for a custom star cursor but didn't say it must never hide the real pointer. The first build hid it and drew a star that didn't follow scrolling; the fix makes the star the real system cursor.

## Problem 10: Push to GitHub and submit the URL

**Prompt 1:**

> thanks I'm good with this for the final step we are going to push it to github but before we are going to make sure everything was done correct, similar to last time please go through and look through all of the previous problems scrub top to bottom and make sure everything was completed to perfection and correctly. Once complete, make sure to follow the expected repo listed in problem 10 and please let me know if anything stands out. Make sure to keep all of the notes that are included with the whole data/ folder and do not commit real .env and use .gitignore and include .env.example with placeholders only. Make sure to put a short note in README.md to show how to run the agent, and its okay if there's additional python files outside of what was desginated the repo. Once confirmed and complete refer back to me so that I give the go ahead for pushing

**Follow-up prompt:** None needed. The first prompt covered everything for this problem.
