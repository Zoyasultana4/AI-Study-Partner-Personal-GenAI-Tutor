"use client";

import { useEffect, useMemo, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

export default function HomePage() {
  const [uploadStatus, setUploadStatus] = useState("Ready to upload.");
  const [documentFile, setDocumentFile] = useState(null);

  const [planDays, setPlanDays] = useState(7);
  const [planText, setPlanText] = useState("Plan results will appear here...");

  const [sessionRunning, setSessionRunning] = useState(false);
  const [sessionSeconds, setSessionSeconds] = useState(0);
  const [sessionMessage, setSessionMessage] = useState("Ready to study. Click Start.");

  const [summaryText, setSummaryText] = useState("Summary results will appear here...");
  const [flashcardsText, setFlashcardsText] = useState("Flashcard results will appear here...");
  const [quizText, setQuizText] = useState("Quiz results will appear here...");

  const [chatSessionId, setChatSessionId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [chatMessages, setChatMessages] = useState([
    { role: "assistant", content: "Hi! Ask me anything about your uploaded syllabus." },
  ]);

  const [reminderTitle, setReminderTitle] = useState("");
  const [reminderDate, setReminderDate] = useState("");
  const [reminderTime, setReminderTime] = useState("");
  const [reminderChannel, setReminderChannel] = useState("local");
  const [telegramChatId, setTelegramChatId] = useState("");
  const [reminderOutput, setReminderOutput] = useState("Reminder status will appear here...");

  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analytics, setAnalytics] = useState(null);

  useEffect(() => {
    if (!sessionRunning) return;
    const timer = setInterval(() => setSessionSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [sessionRunning]);

  useEffect(() => {
    const key = "aiStudyChatSessionId";
    let currentSession = localStorage.getItem(key);
    if (!currentSession) {
      currentSession = `session-${Date.now()}`;
      localStorage.setItem(key, currentSession);
    }
    setChatSessionId(currentSession);
  }, []);

  const sessionClock = useMemo(() => {
    const mm = String(Math.floor(sessionSeconds / 60)).padStart(2, "0");
    const ss = String(sessionSeconds % 60).padStart(2, "0");
    return `${mm}:${ss}`;
  }, [sessionSeconds]);

  async function uploadFile() {
    if (!documentFile) {
      setUploadStatus("Select a file first.");
      return;
    }

    setUploadStatus("Uploading and parsing...");
    const formData = new FormData();
    formData.append("file", documentFile);

    try {
      const res = await fetch(`${API}/upload-document`, {
        method: "POST",
        body: formData,
      });
      const json = await res.json();
      if (!res.ok || json.success === false) {
        setUploadStatus(`Upload failed: ${json.detail || json.error || "Unknown error"}`);
        return;
      }
      setUploadStatus(json.message || `Uploaded ${documentFile.name}`);
      setDocumentFile(null);
    } catch (err) {
      setUploadStatus(`Upload error: ${err.message}`);
    }
  }

  async function generatePlan() {
    setPlanText("Generating study plan...");
    try {
      const res = await fetch(`${API}/study-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: Number(planDays) }),
      });
      const json = await res.json();
      const text = (json.plan || [])
        .map((p) => `Day ${p.day}: ${(p.focus || []).join(", ") || "Review"}`)
        .join("\n");
      setPlanText(text || "No study plan generated.");
    } catch (err) {
      setPlanText(`Error: ${err.message}`);
    }
  }

  async function startSession() {
    setSessionRunning(true);
    setSessionMessage("Timer running...");
  }

  async function stopAndSaveSession() {
    setSessionRunning(false);
    const minutes = Math.floor(sessionSeconds / 60);

    if (minutes < 1) {
      setSessionMessage("Session under 1 minute not saved.");
      return;
    }

    try {
      const res = await fetch(`${API}/study-session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topicCovered: "Next.js session",
          durationMinutes: minutes,
        }),
      });
      if (!res.ok) throw new Error("Could not save session");
      setSessionMessage(`Saved ${minutes} minute(s).`);
      setSessionSeconds(0);
    } catch (err) {
      setSessionMessage(`Save failed: ${err.message}`);
    }
  }

  async function generateSummary() {
    setSummaryText("Generating summary...");
    try {
      const res = await fetch(`${API}/summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ maxSentences: 4 }),
      });
      const json = await res.json();
      setSummaryText(json.summary || "No summary.");
    } catch (err) {
      setSummaryText(`Error: ${err.message}`);
    }
  }

  async function generateFlashcards() {
    setFlashcardsText("Generating flashcards...");
    try {
      const res = await fetch(`${API}/flashcards`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: 5 }),
      });
      const json = await res.json();
      const text = (json.cards || [])
        .map((c, i) => `${i + 1}. Q: ${c.front}\n   A: ${c.back}`)
        .join("\n\n");
      setFlashcardsText(text || "No flashcards.");
    } catch (err) {
      setFlashcardsText(`Error: ${err.message}`);
    }
  }

  async function generateQuiz() {
    setQuizText("Generating quiz...");
    try {
      const res = await fetch(`${API}/quiz`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: 5 }),
      });
      const json = await res.json();
      const text = (json.quiz || [])
        .map((q, i) => `${i + 1}. ${q.question}\n   Answer: ${q.answer}`)
        .join("\n\n");
      setQuizText(text || "No quiz.");
    } catch (err) {
      setQuizText(`Error: ${err.message}`);
    }
  }

  async function sendChatMessage() {
    const question = chatInput.trim();
    if (!question || chatSending) return;

    setChatMessages((prev) => [...prev, { role: "user", content: question }]);
    setChatInput("");
    setChatSending(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          sessionId: chatSessionId || "default",
        }),
      });

      const json = await res.json();
      const answer = json?.answer || "I could not generate a response right now.";
      setChatMessages((prev) => [...prev, { role: "assistant", content: answer }]);
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err.message}` },
      ]);
    } finally {
      setChatSending(false);
    }
  }

  function startNewChat() {
    const key = "aiStudyChatSessionId";
    const newSession = `session-${Date.now()}`;
    localStorage.setItem(key, newSession);
    setChatSessionId(newSession);
    setChatMessages([{ role: "assistant", content: "New chat started. Ask your next question." }]);
  }

  async function fetchTelegramChatId() {
    setReminderOutput("Fetching Telegram chat ID...");
    try {
      const res = await fetch(`${API}/telegram/get-chat-id`, { method: "POST" });
      const json = await res.json();
      if (!json.success) {
        setReminderOutput(json.message || "Could not fetch chat ID.");
        return;
      }
      setTelegramChatId(json.chat_id || "");
      setReminderOutput(`Telegram chat ID ready: ${json.chat_id}`);
    } catch (err) {
      setReminderOutput(`Error: ${err.message}`);
    }
  }

  async function testTelegram() {
    setReminderOutput("Testing Telegram...");
    try {
      const res = await fetch(`${API}/telegram/test`, { method: "POST" });
      const json = await res.json();
      setReminderOutput(json.success ? "Telegram test sent." : `Telegram error: ${json.message}`);
    } catch (err) {
      setReminderOutput(`Error: ${err.message}`);
    }
  }

  async function setReminder() {
    if (!reminderTitle || !reminderDate || !reminderTime) {
      setReminderOutput("Fill title, date, and time.");
      return;
    }

    setReminderOutput("Setting reminder...");
    try {
      const remindAt = new Date(`${reminderDate}T${reminderTime}`).toISOString();
      const payload = {
        title: reminderTitle,
        remindAt,
        channel: reminderChannel,
        ...(reminderChannel === "telegram" && telegramChatId ? { chatId: telegramChatId } : {}),
      };

      const res = await fetch(`${API}/reminders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await res.json();

      if (!res.ok) {
        setReminderOutput(json.detail || "Failed to set reminder.");
        return;
      }

      setReminderOutput(`Reminder set: ${json.reminder?.title}`);
      setReminderTitle("");
      setReminderDate("");
      setReminderTime("");
    } catch (err) {
      setReminderOutput(`Error: ${err.message}`);
    }
  }

  async function refreshAnalytics() {
    setAnalyticsLoading(true);
    try {
      const res = await fetch(`${API}/analytics`);
      const json = await res.json();
      setAnalytics(json);
    } catch {
      setAnalytics(null);
    } finally {
      setAnalyticsLoading(false);
    }
  }

  const studyTime = analytics
    ? `${Math.floor((analytics.totalStudyMinutes || 0) / 60)} hr ${(analytics.totalStudyMinutes || 0) % 60} min`
    : "0 hr 0 min";

  return (
    <main className="app">
      <section className="card">
        <div className="card-header">
          <h1>✨ AI Study Partner</h1>
          <p className="card-subtitle">Personal GenAI Tutor (Next.js frontend)</p>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>💬 AI Tutor Chat</h2>
          <p className="card-subtitle">Multi-turn conversation using your syllabus context</p>
        </div>
        <div className="actions">
          <button onClick={startNewChat}>New Chat</button>
          <span className="card-subtitle">Session: {chatSessionId || "loading..."}</span>
        </div>
        <div className="chat-log">
          {chatMessages.map((m, idx) => (
            <div key={`${m.role}-${idx}`} className={`chat-bubble ${m.role === "user" ? "user" : "assistant"}`}>
              <strong>{m.role === "user" ? "You" : "Tutor"}:</strong> {m.content}
            </div>
          ))}
          {chatSending && <div className="chat-bubble assistant">Tutor is typing...</div>}
        </div>
        <div className="chat-input-row" style={{ marginTop: 10 }}>
          <input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="Ask a question about your notes..."
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                sendChatMessage();
              }
            }}
          />
          <button className="primary" onClick={sendChatMessage} disabled={chatSending || !chatInput.trim()}>
            Send
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>📚 Upload Your Notes</h2>
          <p className="card-subtitle">PDF, DOCX, TXT supported</p>
        </div>
        <input type="file" accept=".pdf,.docx,.txt" onChange={(e) => setDocumentFile(e.target.files?.[0] || null)} />
        <div className="actions" style={{ marginTop: 10 }}>
          <button className="primary" onClick={uploadFile}>Upload</button>
        </div>
        <div className="output">{uploadStatus}</div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>🗓️ Study Plan Generator</h2>
        </div>
        <div className="actions">
          <select value={planDays} onChange={(e) => setPlanDays(Number(e.target.value))}>
            {Array.from({ length: 10 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>{d} day{d > 1 ? "s" : ""}</option>
            ))}
          </select>
          <button className="primary" onClick={generatePlan}>Generate Plan</button>
        </div>
        <div className="output">{planText}</div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>⏱️ Study Session</h2>
        </div>
        <div className="output" style={{ fontSize: 28, textAlign: "center", fontWeight: 700 }}>{sessionClock}</div>
        <div className="actions" style={{ marginTop: 10 }}>
          <button className="primary" onClick={startSession} disabled={sessionRunning}>Start Session</button>
          <button className="danger" onClick={stopAndSaveSession} disabled={!sessionRunning}>Stop & Save</button>
        </div>
        <div className="output">{sessionMessage}</div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>📊 Your Study Materials</h2>
        </div>
        <div className="grid-3">
          <div>
            <div className="actions"><button onClick={generateSummary}>Generate Summary</button></div>
            <div className="output">{summaryText}</div>
          </div>
          <div>
            <div className="actions"><button onClick={generateFlashcards}>Generate Flashcards</button></div>
            <div className="output">{flashcardsText}</div>
          </div>
          <div>
            <div className="actions"><button onClick={generateQuiz}>Generate Quiz</button></div>
            <div className="output">{quizText}</div>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>🔔 Study Reminders <span className="badge">Optional</span></h2>
        </div>
        <div className="row">
          <label>
            Title
            <input value={reminderTitle} onChange={(e) => setReminderTitle(e.target.value)} />
          </label>
          <label>
            Channel
            <select value={reminderChannel} onChange={(e) => setReminderChannel(e.target.value)}>
              <option value="local">Local</option>
              <option value="telegram">Telegram</option>
            </select>
          </label>
          <label>
            Date
            <input type="date" value={reminderDate} onChange={(e) => setReminderDate(e.target.value)} />
          </label>
          <label>
            Time
            <input type="time" value={reminderTime} onChange={(e) => setReminderTime(e.target.value)} />
          </label>
        </div>
        <div className="actions" style={{ marginTop: 10 }}>
          <button className="primary" onClick={setReminder}>Set Reminder</button>
          <button onClick={fetchTelegramChatId}>Get Chat ID</button>
          <button onClick={testTelegram}>Test Telegram</button>
        </div>
        <div className="output">{reminderOutput}</div>
      </section>

      <section className="card">
        <div className="card-header">
          <h2>📈 Analytics & Progress</h2>
          <p className="card-subtitle">Study time, streak, and documents</p>
        </div>
        <div className="actions">
          <button className="primary" onClick={refreshAnalytics}>Refresh Stats</button>
        </div>

        {analyticsLoading && <div className="output">Loading analytics...</div>}

        {!analyticsLoading && analytics && (
          <>
            <div className="stats">
              <div className="stat">
                <div className="label">Study Time</div>
                <div className="value">{studyTime}</div>
              </div>
              <div className="stat">
                <div className="label">Study Streak</div>
                <div className="value">{analytics.studyStreak || 0} days</div>
              </div>
              <div className="stat">
                <div className="label">Documents</div>
                <div className="value">{analytics.documents?.length || 0}</div>
              </div>
            </div>
            <div className="output" style={{ marginTop: 10 }}>
              {(analytics.documents || []).slice(0, 5).map((d) => `• ${d.name}`).join("\n") || "No documents yet."}
            </div>
          </>
        )}

        {!analyticsLoading && !analytics && <div className="output">Click Refresh Stats to load report.</div>}
      </section>
    </main>
  );
}
