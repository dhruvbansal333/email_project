/**
 * AI Commitment Intelligence - Gmail connector (generated for your account)
 *
 * KEEP THE KEY BELOW SECRET. Treat it like a password: don't share this script
 * or post it anywhere. If it leaks, generate a new key on the Connect Gmail page
 * (the old key stops working immediately).
 *
 * What it does:
 *  - Every 5 minutes it looks ONLY at Gmail threads you have labeled "CommitmentAI-Send".
 *  - It sends the text of the newest message in each (first 8,000 characters) to the
 *    app. The app extracts and ranks the commitments and shows them on your dashboard.
 *  - Then it adds the label "CommitmentAI-Done" so that thread is never sent twice.
 *  - If an email can never be processed (too long to read, rejected, or it failed 3
 *    times) it gets "CommitmentAI-Failed" and is left alone.
 *  It never sends, edits or deletes any email. It only adds its own three labels.
 *
 * Setup: pick the function "setup" in the toolbar, click Run, and approve the permissions.
 */

const API_URL = "https://YOUR-API-SERVICE.onrender.com/process";
const API_KEY = "PASTE_YOUR_KEY_HERE";

const SEND_LABEL = "CommitmentAI-Send";
const DONE_LABEL = "CommitmentAI-Done";
const FAILED_LABEL = "CommitmentAI-Failed";
const HANDLER = "processLabeledEmails";
const TRIGGER_MINUTES = 5;
const MAX_THREADS_PER_RUN = 5;
const MAX_CHARS = 8000;
const MAX_ATTEMPTS = 3;

// Run this ONCE: creates the labels and the 5-minute timer. Safe to run again.
function setup() {
  [SEND_LABEL, DONE_LABEL, FAILED_LABEL].forEach(function (name) {
    if (!GmailApp.getUserLabelByName(name)) {
      GmailApp.createLabel(name);
      Logger.log("Created label: " + name);
    }
  });
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === HANDLER) {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger(HANDLER).timeBased().everyMinutes(TRIGGER_MINUTES).create();
  Logger.log("Ready. Label any email '" + SEND_LABEL + "' and it will be picked up within " +
             TRIGGER_MINUTES + " minutes.");
}

// Runs automatically every 5 minutes (you can also run it by hand to test).
function processLabeledEmails() {
  if (!API_KEY || API_KEY.indexOf("cai_") !== 0) {
    Logger.log("No API key set. Generate one on the app's Connect Gmail page and paste it into API_KEY.");
    return;
  }
  const doneLabel = GmailApp.getUserLabelByName(DONE_LABEL);
  const failedLabel = GmailApp.getUserLabelByName(FAILED_LABEL);
  if (!GmailApp.getUserLabelByName(SEND_LABEL) || !doneLabel || !failedLabel) {
    Logger.log("Labels are missing. Run the function 'setup' once first.");
    return;
  }

  // Never let two runs overlap (the timer firing while you press Run, or a slow run
  // outlasting 5 minutes): that could send the same email twice.
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    Logger.log("Another run is still in progress; skipping this one.");
    return;
  }
  try {
    processThreads_(doneLabel, failedLabel);
  } finally {
    lock.releaseLock();
  }
}

// The actual work. Only ever called while holding the lock.
function processThreads_(doneLabel, failedLabel) {
  const props = PropertiesService.getScriptProperties();
  const query = "label:" + SEND_LABEL + " -label:" + DONE_LABEL + " -label:" + FAILED_LABEL;
  const threads = GmailApp.search(query, 0, MAX_THREADS_PER_RUN);
  Logger.log("Found " + threads.length + " labeled email thread(s) to process.");

  for (let i = 0; i < threads.length; i++) {
    const thread = threads[i];
    const id = thread.getId();
    const attemptsKey = "attempts_" + id;
    const messages = thread.getMessages();
    const text = String(messages[messages.length - 1].getPlainBody() || "").trim().substring(0, MAX_CHARS);

    if (!text) {
      thread.addLabel(doneLabel);          // nothing to read in it
      Logger.log("Thread " + id + ": empty, marked done.");
      continue;
    }

    const result = callApi_(text);
    const outcome = classify_(result);

    if (outcome === "ok") {
      thread.addLabel(doneLabel);
      props.deleteProperty(attemptsKey);
      Logger.log("Thread " + id + ": processed.");
    } else if (outcome === "fail") {
      thread.addLabel(failedLabel);        // this email can never work; don't retry it
      props.deleteProperty(attemptsKey);
      Logger.log("Thread " + id + ": rejected by the app (" + result.code + "), marked failed. " + detail_(result));
    } else if (outcome === "attempt") {
      const attempts = Number(props.getProperty(attemptsKey) || 0) + 1;
      if (attempts >= MAX_ATTEMPTS) {
        thread.addLabel(failedLabel);      // keeps one bad email from using your daily quota forever
        props.deleteProperty(attemptsKey);
        Logger.log("Thread " + id + ": failed " + attempts + " times, marked failed.");
      } else {
        props.setProperty(attemptsKey, String(attempts));
        Logger.log("Thread " + id + ": attempt " + attempts + " of " + MAX_ATTEMPTS + " failed; will retry. " + detail_(result));
      }
    } else {
      // "stop": a problem that affects every email (server asleep, limit reached, bad key...).
      // Leave everything unlabeled and try again at the next run.
      Logger.log("Stopping this run (code " + result.code + "). " + detail_(result) +
                 (result.code === 401 ? " -> Your key was rejected: generate a new one and paste it into API_KEY." : ""));
      break;
    }
  }
}

function callApi_(text) {
  try {
    const response = UrlFetchApp.fetch(API_URL, {
      method: "post",
      contentType: "application/json",
      headers: { "X-API-Key": API_KEY },
      payload: JSON.stringify({ text: text, source: "gmail" }),
      muteHttpExceptions: true
    });
    return { code: response.getResponseCode(), body: response.getContentText() };
  } catch (err) {
    return { code: 0, body: "" };          // network error or timeout
  }
}

// Decide what to do with the app's answer.
//  ok      - done
//  fail    - this particular email will never work (empty/too long/invalid): mark failed
//  attempt - the AI step failed for this email: count it, retry, give up after MAX_ATTEMPTS
//  stop    - not this email's fault: wait for the next run (nothing is labeled or counted)
function classify_(r) {
  if (r.code === 200) return "ok";
  if (r.code === 0) return "stop";
  let hasDetail = false;
  try { hasDetail = !!JSON.parse(r.body).detail; } catch (e) {}
  if (!hasDetail) return "stop";           // not an answer from the app (e.g. the server is waking up)
  if (r.code === 400 || r.code === 413 || r.code === 422) return "fail";
  if (r.code >= 500 && r.code !== 503) return "attempt";
  return "stop";                           // 401 bad key, 429 limit reached, 503 paused, anything unexpected
}

function detail_(r) {
  try { return String(JSON.parse(r.body).detail || ""); } catch (e) { return ""; }
}
