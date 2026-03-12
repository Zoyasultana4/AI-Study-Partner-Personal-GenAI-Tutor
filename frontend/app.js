const API = "http://localhost:8000/api";
let telegramChatId = "";

// Utility to update element text
function setStatus(id, text, isError = false) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text;
    el.style.color = isError ? "#e53e3e" : "#38a169";
    console.log(`[${id}]`, text);
  }
}

// ==================== MANUAL SESSION TIMER (START / STOP) ====================
let sessionStartTime = null;
let elapsedBeforeStart = 0;
let totalStudySeconds = 0;
let sessionTimer = null;
let sessionRunning = false;

const sessionTimeEl = document.getElementById("sessionTime");
const sessionTimerStatusEl = document.getElementById("sessionTimerStatus");
const startTimerBtn = document.getElementById("startTimerBtn");
const stopTimerBtn = document.getElementById("stopTimerBtn");

function renderTimer(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (sessionTimeEl) {
    sessionTimeEl.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
}

function updateSessionDisplay() {
  if (!sessionRunning || !sessionStartTime) return;
  totalStudySeconds = elapsedBeforeStart + Math.floor((Date.now() - sessionStartTime) / 1000);
  renderTimer(totalStudySeconds);
}

async function saveSession(durationSeconds) {
  const minutes = Math.floor(durationSeconds / 60);
  if (minutes < 1) {
    if (sessionTimerStatusEl) {
      sessionTimerStatusEl.textContent = "Session under 1 minute was not saved.";
    }
    return;
  }

  try {
    const response = await fetch(`${API}/study-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topicCovered: "Manual study session",
        durationMinutes: minutes,
      }),
    });
    const data = await response.json();
    if (sessionTimerStatusEl) {
      sessionTimerStatusEl.textContent = `Saved ${minutes} minute(s). Total: ${data.totalMinutes || minutes} minute(s).`;
    }
  } catch (err) {
    if (sessionTimerStatusEl) {
      sessionTimerStatusEl.textContent = `Failed to save session: ${err.message}`;
    }
  }
}

startTimerBtn?.addEventListener("click", () => {
  if (sessionRunning) return;
  sessionRunning = true;
  sessionStartTime = Date.now();
  sessionTimer = setInterval(updateSessionDisplay, 1000);
  if (startTimerBtn) startTimerBtn.disabled = true;
  if (stopTimerBtn) stopTimerBtn.disabled = false;
  if (sessionTimerStatusEl) sessionTimerStatusEl.textContent = "Timer running... Click Stop when you finish.";
});

stopTimerBtn?.addEventListener("click", async () => {
  if (!sessionRunning) return;

  sessionRunning = false;
  if (sessionTimer) {
    clearInterval(sessionTimer);
    sessionTimer = null;
  }

  const finalSeconds = elapsedBeforeStart + Math.floor((Date.now() - sessionStartTime) / 1000);
  totalStudySeconds = finalSeconds;
  elapsedBeforeStart = 0;
  sessionStartTime = null;

  renderTimer(finalSeconds);
  if (startTimerBtn) startTimerBtn.disabled = false;
  if (stopTimerBtn) stopTimerBtn.disabled = true;

  await saveSession(finalSeconds);

  // Reset display after save for next session
  totalStudySeconds = 0;
  renderTimer(0);
  if (sessionTimerStatusEl) {
    sessionTimerStatusEl.textContent = "Timer is idle. Click Start when you begin studying.";
  }
});


// ==================== DOCUMENT UPLOAD ====================
document.getElementById("uploadArea")?.addEventListener("click", function() {
  const fileInput = document.getElementById("documentInput");
  if (fileInput) fileInput.click();
});

document.getElementById("uploadArea")?.addEventListener("dragover", function(e) {
  e.preventDefault();
  this.style.background = "linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(139, 92, 246, 0.15) 100%)";
});

document.getElementById("uploadArea")?.addEventListener("dragleave", function(e) {
  e.preventDefault();
  this.style.background = "linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%)";
});

document.getElementById("uploadArea")?.addEventListener("drop", function(e) {
  e.preventDefault();
  this.style.background = "linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(139, 92, 246, 0.05) 100%)";
  const files = e.dataTransfer.files;
  if (files.length > 0) {
    document.getElementById("documentInput").files = files;
    uploadFile();
  }
});

document.getElementById("documentInput")?.addEventListener("change", uploadFile);

async function uploadFile() {
  const fileInput = document.getElementById("documentInput");
  const file = fileInput?.files?.[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  setStatus("documentStatus", "📤 Uploading and parsing...");
  try {
    const response = await fetch(`${API}/upload-document`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (response.ok) {
      setStatus("documentStatus", `✅ Uploaded: ${file.name} (${data.wordCount || 0} words)`, false);
      fileInput.value = "";
    } else {
      setStatus("documentStatus", `❌ ${data.detail || "Upload failed"}`, true);
    }
  } catch (err) {
    setStatus("documentStatus", `❌ ${err.message}`, true);
  }
}

// ==================== QUICK ACTIONS (SUMMARY OR QUIZ) ====================
document.getElementById("quickSummaryBtn")?.addEventListener("click", async function() {
  setStatus("quickActionOutput", "📄 Generating summary...");
  
  try {
    const res = await fetch(`${API}/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maxSentences: 5 }),
    });
    const json = await res.json();
    
    const el = document.getElementById("quickActionOutput");
    if (el) {
      el.innerHTML = `<strong>📝 Summary:</strong><br><br>${json.summary || "No summary available. Upload a document first."}`;
      el.style.color = "#2d3748";
    }
  } catch (err) {
    setStatus("quickActionOutput", `❌ ${err.message}`, true);
  }
});

document.getElementById("quickQuizBtn")?.addEventListener("click", async function() {
  setStatus("quickActionOutput", "❓ Generating quiz...");
  
  try {
    const res = await fetch(`${API}/quiz`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 5 }),
    });
    const json = await res.json();
    
    if (!json.quiz?.length) {
      setStatus("quickActionOutput", "❌ No quiz available. Upload a document first.", true);
      return;
    }
    
    const el = document.getElementById("quickActionOutput");
    if (!el) return;
    
    let quizHtml = `
      <div style="margin-bottom: 20px;">
        <h3 style="color: #667eea; margin: 0; display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 1.5rem;">📚</span>
          Interactive Quiz
        </h3>
        <p style="color: #666; margin: 8px 0 0 0; font-size: 0.9rem;">
          ${json.quiz.length} questions • Click "Show Answer" to reveal
        </p>
      </div>
    `;
    
    json.quiz.forEach((q, i) => {
      // Shuffle options if available
      const options = q.options ? [...q.options].sort(() => Math.random() - 0.5) : [];
      
      quizHtml += `
        <div style="margin-bottom: 20px; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
          <!-- Question Header -->
          <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 18px; display: flex; align-items: flex-start; gap: 15px;">
            <div style="display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; background: rgba(255,255,255,0.2); border-radius: 50%; flex-shrink: 0; font-weight: bold; font-size: 1.1rem;">
              Q${i + 1}
            </div>
            <div style="flex: 1;">
              <p style="margin: 0; font-weight: 500; font-size: 1rem; line-height: 1.4;">
                ${q.question}
              </p>
            </div>
          </div>
          
          <!-- Answer Section -->
          <div style="background: #f8f9fa; padding: 20px;">
            <button 
              onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'block' : 'none'; this.textContent = this.textContent === '✓ Show Answer' ? '✗ Hide Answer' : '✓ Show Answer';"
              style="background: #38a169; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.95rem; transition: all 0.3s; margin-bottom: 12px;"
              onmouseover="this.style.background='#2f855a'"
              onmouseout="this.style.background='#38a169'"
            >
              ✓ Show Answer
            </button>
            
            <div style="display: none; padding: 16px; background: white; border-radius: 8px; border-left: 4px solid #38a169;">
              <p style="margin: 0 0 12px 0; color: #666; font-size: 0.85rem; font-weight: 600;">ANSWER:</p>
              <p style="margin: 0 0 12px 0; color: #2d3748; font-size: 0.95rem; line-height: 1.5;">
                ${q.answer}
              </p>
              ${q.explanation ? `
                <div style="padding-top: 12px; border-top: 1px solid #e2e8f0;">
                  <p style="margin: 0; color: #667eea; font-size: 0.85rem;">
                    <strong>Why:</strong> ${q.explanation}
                  </p>
                </div>
              ` : ''}
            </div>
          </div>
        </div>
      `;
    });
    
    el.innerHTML = quizHtml;
    el.style.color = "#2d3748";
    el.style.whiteSpace = "normal";
    el.style.lineHeight = "1.4";
  } catch (err) {
    setStatus("quickActionOutput", `❌ ${err.message}`, true);
  }
});

// ==================== PERSONALIZED STUDY PLAN ====================
document.getElementById("generatePlanBtn")?.addEventListener("click", async function() {
  const days = parseInt(document.getElementById("planDays")?.value || 7);
  
  setStatus("planOutput", "📅 Generating...");
  
  try {
    const res = await fetch(`${API}/study-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days }),
    });
    const json = await res.json();
    
    if (!json.plan?.length) {
      setStatus("planOutput", "❌ Upload content first", true);
      return;
    }

    const text = json.plan.map(p => {
      const items = (p.focus || []).length
        ? p.focus.map(topic => `<li>${topic}</li>`).join("")
        : "<li>Review previous concepts</li>";

      return `
        <div style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
          <strong style="color: #667eea; font-size: 0.95rem;">Day ${p.day}</strong>
          <ul style="margin: 6px 0 0 20px; padding: 0; font-size: 0.9rem; line-height: 1.4;">${items}</ul>
        </div>
      `;
    }).join("");

    const el = document.getElementById("planOutput");
    if (el) {
      el.innerHTML = text;
      el.style.color = "#2d3748";
    }
  } catch (err) {
    setStatus("planOutput", `❌ ${err.message}`, true);
  }
});

// ==================== CREATE REMINDER ====================
document.getElementById("reminderBtn")?.addEventListener("click", async function() {
  const title = document.getElementById("reminderTitle")?.value?.trim();
  const date = document.getElementById("reminderDate")?.value;
  const time = document.getElementById("reminderTime")?.value;
  const channel = document.getElementById("reminderChannel")?.value || "local";
  
  if (!title || !date || !time) {
    setStatus("reminderOutput", "❌ Please fill in all fields (title, date, and time)", true);
    return;
  }
  
  // Combine date and time into ISO format
  const reminderDateTime = new Date(`${date}T${time}`).toISOString();
  
  setStatus("reminderOutput", "⏰ Setting reminder...");
  
  try {
    const payload = {
      title,
      remindAt: reminderDateTime,
      channel,
      ...(channel === "telegram" && telegramChatId ? { chatId: telegramChatId } : {}),
    };

    const res = await fetch(`${API}/reminders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const json = await res.json();

    if (!res.ok) {
      setStatus("reminderOutput", `❌ ${json.detail || "Failed to set reminder"}`, true);
      return;
    }
    
    setStatus("reminderOutput", `✅ Reminder set for ${date} at ${time}\n"${json.reminder?.title}"`);
    document.getElementById("reminderTitle").value = "";
    document.getElementById("reminderDate").value = "";
    document.getElementById("reminderTime").value = "";
  } catch (err) {
    setStatus("reminderOutput", `❌ ${err.message}`, true);
  }
});

// ==================== GET CHAT ID FROM TELEGRAM ====================
document.getElementById("getChatIdBtn")?.addEventListener("click", async function() {
  setStatus("reminderOutput", "🔍 Fetching chat ID from Telegram...");
  
  try {
    const res = await fetch(`${API}/telegram/get-chat-id`, { method: "POST" });
    const json = await res.json();
    
    const el = document.getElementById("reminderOutput");
    if (el) {
      if (json.success) {
        telegramChatId = json.chat_id || "";
        el.innerHTML = `<div style="color: #10b981; font-weight: 500;">
          ✅ <strong>Chat ID Found!</strong><br><br>
          <code style="background: #f0fdf4; padding: 8px 12px; border-radius: 6px; display: inline-block; font-family: monospace;">
            ${json.chat_id}
          </code><br><br>
          <small style="color: #6b7280;">
            Your chat ID has been automatically updated. You can now use Telegram reminders!
          </small>
        </div>`;
      } else {
        el.innerHTML = `<div style="color: #ef4444; font-weight: 500;">
          ❌ <strong>${json.message}</strong><br><br>
          <small style="color: #6b7280; line-height: 1.6;">
            Steps to get your chat ID:<br>
            1. Open Telegram<br>
            2. Find your bot (search for its username)<br>
            3. Send it any message (e.g., "/start")<br>
            4. Click "Get Chat ID from Telegram" again<br><br>
            Bot token is configured ✓
          </small>
        </div>`;
      }
    }
  } catch (err) {
    setStatus("reminderOutput", `❌ Error: ${err.message}`, true);
  }
});

// ==================== TEST TELEGRAM ====================
document.getElementById("telegramTestBtn")?.addEventListener("click", async function() {
  setStatus("reminderOutput", "📱 Testing Telegram...");
  
  try {
    const res = await fetch(`${API}/telegram/test`, { method: "POST" });
    const json = await res.json();
    
    if (json.success) {
      setStatus("reminderOutput", `✅ ${json.message || "Telegram test sent successfully!"}`);
    } else {
      const el = document.getElementById("reminderOutput");
      if (el) {
        el.innerHTML = `<div style="color: #ef4444; font-weight: 500;">
          ❌ <strong>Telegram not configured correctly</strong><br><br>
          <small style="display: block; margin-bottom: 10px; color: #991b1b;">
            ${json.message || "Unknown Telegram error"}
          </small>
          <small style="color: #6b7280; line-height: 1.6;">
            To use Telegram:<br>
            1. Start a conversation with your bot<br>
            2. Send any message to the bot<br>
            3. The correct Chat ID will be fetched<br><br>
            Check the server logs for detailed error information.
          </small>
        </div>`;
      }
    }
  } catch (err) {
    setStatus("reminderOutput", `❌ Error: ${err.message}`, true);
  }
});

// ==================== GENERATE SUMMARY ====================
document.getElementById("summaryGenBtn")?.addEventListener("click", async function() {
  setStatus("summaryOutput", "📄 Generating...");
  
  try {
    const res = await fetch(`${API}/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ maxSentences: 4 }),
    });
    const json = await res.json();
    
    const el = document.getElementById("summaryOutput");
    if (el) {
      el.textContent = json.summary || "No summary available";
      el.style.color = "#2d3748";
    }
  } catch (err) {
    setStatus("summaryOutput", `❌ ${err.message}`, true);
  }
});

// ==================== GENERATE FLASHCARDS ====================
document.getElementById("flashcardBtn")?.addEventListener("click", async function() {
  setStatus("flashcardOutput", "🎯 Generating...");
  
  try {
    const res = await fetch(`${API}/flashcards`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 5 }),
    });
    const json = await res.json();
    
    if (!json.cards?.length) {
      setStatus("flashcardOutput", "❌ No flashcards available", true);
      return;
    }
    
    const text = json.cards
      .map((c, i) => `${i + 1}. Q: ${c.front}\n   A: ${c.back}`)
      .join("\n\n");
    
    const el = document.getElementById("flashcardOutput");
    if (el) {
      el.textContent = text;
      el.style.color = "#2d3748";
    }
  } catch (err) {
    setStatus("flashcardOutput", `❌ ${err.message}`, true);
  }
});

// ==================== GENERATE QUIZ ====================
document.getElementById("quizBtn")?.addEventListener("click", async function() {
  setStatus("quizOutput", "❓ Generating...");
  
  try {
    const res = await fetch(`${API}/quiz`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count: 5 }),
    });
    const json = await res.json();
    
    if (!json.quiz?.length) {
      setStatus("quizOutput", "❌ No quiz available", true);
      return;
    }
    
    const text = json.quiz
      .map((q, i) => `${i + 1}. ${q.question}\n   ✓ ${q.answer}`)
      .join("\n\n");
    
    const el = document.getElementById("quizOutput");
    if (el) {
      el.textContent = text;
      el.style.color = "#2d3748";
    }
  } catch (err) {
    setStatus("quizOutput", `❌ ${err.message}`, true);
  }
});

// ==================== SAVE QUIZ SCORE ====================
document.getElementById("saveQuizBtn")?.addEventListener("click", async function() {
  const score = prompt("Enter score (0-100):");
  if (score === null) return;
  
  const correct = prompt("Correct answers:");
  if (correct === null) return;
  
  setStatus("quizOutput", "💾 Saving...");
  
  try {
    const res = await fetch(`${API}/quiz-attempt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        score: parseInt(score),
        totalQuestions: 5,
        correctAnswers: parseInt(correct),
      }),
    });
    const json = await res.json();
    
    setStatus("quizOutput", `✅ Saved: ${json.attempt?.score}`);
  } catch (err) {
    setStatus("quizOutput", `❌ ${err.message}`, true);
  }
});

// ==================== ANALYTICS DASHBOARD ====================
document.getElementById("analyticsBtn")?.addEventListener("click", async function() {
  setStatus("analyticsOutput", "📊 Loading...");
  
  try {
    const res = await fetch(`${API}/analytics`);
    const json = await res.json();
    
    // Build analytics HTML
    const analyticsHtml = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px;">
          <p style="margin: 0; font-size: 0.85rem; opacity: 0.9; text-transform: uppercase; font-weight: 600;">Total Attempts</p>
          <p style="margin: 8px 0 0 0; font-size: 2.2rem; font-weight: bold;">${json.totalAttempts}</p>
        </div>
        
        <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 20px; border-radius: 12px;">
          <p style="margin: 0; font-size: 0.85rem; opacity: 0.9; text-transform: uppercase; font-weight: 600;">Average Score</p>
          <p style="margin: 8px 0 0 0; font-size: 2.2rem; font-weight: bold;">${json.averageScore}%</p>
        </div>
        
        <div style="background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); color: white; padding: 20px; border-radius: 12px;">
          <p style="margin: 0; font-size: 0.85rem; opacity: 0.9; text-transform: uppercase; font-weight: 600;">Study Streak</p>
          <p style="margin: 8px 0 0 0; font-size: 2.2rem; font-weight: bold;">🔥 ${json.studyStreak}</p>
        </div>
        
        <div style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; padding: 20px; border-radius: 12px;">
          <p style="margin: 0; font-size: 0.85rem; opacity: 0.9; text-transform: uppercase; font-weight: 600;">Study Time</p>
          <p style="margin: 8px 0 0 0; font-size: 2.2rem; font-weight: bold;">${Math.floor(json.totalStudyMinutes / 60)}h ${json.totalStudyMinutes % 60}m</p>
        </div>
      </div>
      
      <div style="margin-top: 24px; padding-top: 24px; border-top: 1px solid #e5e7eb;">
        <h3 style="margin: 0 0 16px 0; color: #2d3748; font-size: 1.1rem;">📄 Documents Uploaded</h3>
        <p style="margin: 0; color: #6b7280; font-size: 0.95rem;">
          ${json.documents.length} document${json.documents.length !== 1 ? 's' : ''} uploaded
        </p>
        ${json.documents.length > 0 ? `
          <div style="margin-top: 12px;">
            ${json.documents.slice(0, 5).map(doc => `
              <div style="padding: 8px 0; border-bottom: 1px solid #f0f0f0; font-size: 0.9rem; color: #6b7280;">
                📋 ${doc.name} (${(doc.size / 1024).toFixed(1)} KB)
              </div>
            `).join('')}
            ${json.documents.length > 5 ? `<div style="padding: 8px 0; color: #999; font-size: 0.85rem;">+${json.documents.length - 5} more</div>` : ''}
          </div>
        ` : '<p style="color: #999; margin-top: 8px;">No documents yet</p>'}
      </div>
    `;
    
    const el = document.getElementById("analyticsOutput");
    if (el) {
      el.innerHTML = analyticsHtml;
      el.style.color = "#2d3748";
    }
    
    // Build achievements HTML
    if (json.achievements?.length > 0) {
      const achievementsHtml = `
        <div style="padding-top: 24px; border-top: 1px solid #e5e7eb;">
          <h3 style="margin: 0 0 16px 0; color: #2d3748; font-size: 1.1rem;">🏆 Achievements Unlocked</h3>
          <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px;">
            ${json.achievements.map(achievement => `
              <div style="background: linear-gradient(135deg, #ffd89b 0%, #19547b 100%); color: white; padding: 16px; border-radius: 12px; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <div style="font-size: 2.5rem; margin-bottom: 8px;">🏅</div>
                <p style="margin: 0; font-weight: 600; font-size: 0.9rem; line-height: 1.3;">${achievement.name}</p>
              </div>
            `).join('')}
          </div>
        </div>
      `;
      
      const ach = document.getElementById("achievementsOutput");
      if (ach) {
        ach.innerHTML = achievementsHtml;
        ach.style.color = "#2d3748";
      }
    } else {
      const ach = document.getElementById("achievementsOutput");
      if (ach) {
        ach.innerHTML = `
          <div style="padding-top: 24px; border-top: 1px solid #e5e7eb;">
            <h3 style="margin: 0 0 16px 0; color: #2d3748; font-size: 1.1rem;">🏆 Achievements Unlocked</h3>
            <p style="color: #999; margin: 0;">No achievements unlocked yet. Keep studying! 📚</p>
          </div>
        `;
      }
    }
  } catch (err) {
    setStatus("analyticsOutput", `❌ ${err.message}`, true);
  }
});

console.log("✅ All buttons are ready to use!");

