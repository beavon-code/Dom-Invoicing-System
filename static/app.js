(() => {
  "use strict";

  const DEFAULT_API_BASE = "http://127.0.0.1:8000";
  const $ = (selector) => document.querySelector(selector);

  const state = {
    apiBase: (localStorage.getItem("domAiApiBase") || DEFAULT_API_BASE).replace(/\/$/, ""),
    threadId: null,
    threads: [],
    busy: false,
    uploadedDocument: null,
    uploading: false
  };

  const els = {
    threadList: $("#threadList"),
    messages: $("#messages"),
    welcome: $("#welcomeScreen"),
    input: $("#messageInput"),
    send: $("#sendButton"),
    title: $("#currentTitle"),
    typing: $("#typingIndicator"),
    connection: $("#connectionLabel"),
    chatArea: $("#chatArea"),
    sidebar: $("#sidebar"),
    settingsModal: $("#settingsModal"),
    apiInput: $("#apiBaseInput")
  };

  function toast(message, type = "success") {
    const item = document.createElement("div");
    item.className = `toast ${type === "error" ? "error" : ""}`;
    item.textContent = message;
    $("#toastContainer").appendChild(item);
    setTimeout(() => item.remove(), 3600);
  }

  async function api(path, options = {}) {
    const response = await fetch(`${state.apiBase}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {})
      }
    });
    let data;
    try { data = await response.json(); }
    catch { data = {}; }
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`;
      throw new Error(detail);
    }
    return data;
  }

  function setBusy(busy) {
    state.busy = busy;
    els.send.disabled = busy || (!els.input.value.trim() && !state.uploadedDocument);
    els.input.disabled = busy;
    els.typing.classList.toggle("hidden", !busy);
    if (busy) {
      els.typing.classList.remove("hidden");
      scrollToBottom();
    }
  }

  function scrollToBottom() {
    requestAnimationFrame(() => { els.chatArea.scrollTop = els.chatArea.scrollHeight; });
  }

  function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const now = new Date();
    const sameDay = date.toDateString() === now.toDateString();
    return sameDay ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function safeMarkdown(content) {
    const raw = window.marked
      ? marked.parse(String(content || ""), { breaks: true, gfm: true })
      : escapeHtml(String(content || "")).replace(/\n/g, "<br>");
    return window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
  }

  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[ch]);
  }

  function addMessage(role, content) {
    const isUser = role === "human" || role === "user";
    const row = document.createElement("article");
    row.className = `message-row ${isUser ? "user" : "assistant"}`;

    if (!isUser) {
      const avatar = document.createElement("div");
      avatar.className = "assistant-avatar";
      avatar.textContent = "✦";
      row.appendChild(avatar);
    }

    const contentWrap = document.createElement("div");
    contentWrap.className = "message-content";

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = isUser ? "You" : "Dom Invoicing AI";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = safeMarkdown(content);

    contentWrap.append(meta, bubble);
    row.appendChild(contentWrap);
    els.messages.appendChild(row);
    return row;
  }

  function resetChatView() {
    els.messages.innerHTML = "";
    els.welcome.classList.toggle("hidden", Boolean(state.threadId));
    els.title.textContent = "New conversation";
  }

  function renderThreads() {
    els.threadList.innerHTML = "";
    if (!state.threads.length) {
      const empty = document.createElement("div");
      empty.className = "sidebar-loading";
      empty.textContent = "No conversations yet.";
      els.threadList.appendChild(empty);
      return;
    }

    state.threads.forEach((thread) => {
      const item = document.createElement("div");
      item.className = `thread-item ${thread.thread_id === state.threadId ? "selected" : ""}`;

      const select = document.createElement("button");
      select.className = "thread-select";
      select.type = "button";
      select.textContent = thread.title || "New conversation";
      select.title = thread.title || "New conversation";
      select.addEventListener("click", () => openThread(thread.thread_id));

      const menu = document.createElement("button");
      menu.className = "thread-menu";
      menu.type = "button";
      menu.textContent = "···";
      menu.title = "Rename conversation";
      menu.addEventListener("click", (event) => {
        event.stopPropagation();
        renameThread(thread);
      });

      item.append(select, menu);
      els.threadList.appendChild(item);
    });
  }

  async function loadThreads() {
    try {
      const data = await api("/threads");
      state.threads = Array.isArray(data.threads) ? data.threads : [];
      renderThreads();
      els.connection.textContent = "Connected to backend";
      return true;
    } catch (error) {
      els.threadList.innerHTML = '<div class="sidebar-loading">Could not load conversations.</div>';
      els.connection.textContent = "Backend unavailable";
      return false;
    }
  }

  async function createThread() {
    try {
      const data = await api("/threads", {
        method: "POST",
        body: JSON.stringify({ title: "New Conversation" })
      });
      state.threadId = data.thread_id;
      resetChatView();
      els.welcome.classList.remove("hidden");
      renderThreads();
      els.input.focus();
      closeSidebarOnMobile();
      return true;
    } catch (error) {
      toast(error.message, "error");
      return false;
    }
  }

  async function openThread(threadId) {
    if (state.busy) return;
    try {
      const data = await api(`/threads/${encodeURIComponent(threadId)}`);
      state.threadId = threadId;
      els.messages.innerHTML = "";
      els.welcome.classList.add("hidden");
      els.title.textContent = data.thread?.title || "Conversation";
      (data.messages || []).forEach((message) => {
        if (message.role === "human" || message.role === "user") addMessage("user", message.content);
        else if (message.role === "ai" || message.role === "assistant") {
          if (message.content) addMessage("assistant", message.content);
        }
      });
      renderThreads();
      scrollToBottom();
      closeSidebarOnMobile();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function renameThread(thread) {
    const current = thread.title || "";
    const title = window.prompt("Enter a new conversation title:", current);
    if (title === null) return;
    const clean = title.trim();
    if (!clean) return toast("The conversation title cannot be empty.", "error");
    try {
      await api(`/threads/${encodeURIComponent(thread.thread_id)}`, {
        method: "PATCH",
        body: JSON.stringify({ title: clean })
      });
      if (state.threadId === thread.thread_id) els.title.textContent = clean;
      await loadThreads();
      toast("Conversation renamed.");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function sendMessage(prefilledText) {
    if (state.busy) return;
    let message = (prefilledText ?? els.input.value).trim();
    if (!message && state.uploadedDocument) {
      message = "Please analyze the uploaded purchase order. Extract the customer details, PO number, dates, line items, quantities, unit prices, VAT rates and totals. Check for discrepancies and present a verification summary. Do not generate an invoice until I explicitly ask you to.";
    }
    if (!message) return;

    if (state.uploadedDocument) {
      message += `\n\nUploaded document path: ${state.uploadedDocument.file_path}\nOriginal filename: ${state.uploadedDocument.file_name}\nPlease use the add_rag tool with this file path to inspect the uploaded document before answering.`;
    }

    // Create a server-side thread first so that the request always has a stable thread ID.
    if (!state.threadId) {
      const created = await createThread();
      if (!created) return;
    }

    els.welcome.classList.add("hidden");
    addMessage("user", message);
    els.input.value = "";
    resizeInput();
    setBusy(true);

    try {
      const data = await api("/chat", {
        method: "POST",
        body: JSON.stringify({ message, thread_id: state.threadId })
      });
      if (data.thread_id) state.threadId = data.thread_id;
      if (typeof data.response === "string" && data.response.trim()) {
        addMessage("assistant", data.response);
      } else {
        addMessage("assistant", "The agent completed the request but returned an empty text response.");
      }
      if (state.uploadedDocument) clearUploadedDocument();
      await loadThreads();
      const active = state.threads.find((thread) => thread.thread_id === state.threadId);
      if (active) els.title.textContent = active.title;
    } catch (error) {
      addMessage("assistant", `**I couldn't complete that request.**\n\n${error.message}`);
      toast(error.message, "error");
    } finally {
      setBusy(false);
      els.input.disabled = false;
      els.input.focus();
      scrollToBottom();
    }
  }

  function clearUploadedDocument() {
    state.uploadedDocument = null;
    $("#attachedFile").classList.add("hidden");
    $("#attachedFileName").textContent = "";
    $("#attachedFileStatus").textContent = "Ready to analyze";
    $("#fileInput").value = "";
    resizeInput();
  }

  async function uploadDocument(file) {
    if (!file) return;
    const allowed = [".pdf", ".docx"];
    const lowerName = file.name.toLowerCase();
    if (!allowed.some((extension) => lowerName.endsWith(extension))) {
      toast("Please upload a PDF or DOCX file.", "error");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      toast("The file is larger than the 20 MB upload limit.", "error");
      return;
    }
    if (state.uploading || state.busy) return;

    state.uploading = true;
    const chip = $("#attachedFile");
    chip.classList.remove("hidden");
    $("#attachedFileName").textContent = file.name;
    $("#attachedFileStatus").textContent = "Uploading...";
    $("#attachedFileStatus").classList.add("upload-progress");
    $("#uploadButton").disabled = true;

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch(`${state.apiBase}/upload`, {
        method: "POST",
        body: formData
      });
      let data = {};
      try { data = await response.json(); } catch {}
      if (!response.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : `Upload failed (${response.status})`);
      }
      state.uploadedDocument = {
        file_path: data.file_path,
        file_name: data.file_name || file.name,
        upload_id: data.upload_id
      };
      $("#attachedFileName").textContent = data.file_name || file.name;
      $("#attachedFileStatus").textContent = "Uploaded · ready";
      $("#attachedFileStatus").classList.remove("upload-progress");
      toast("Document uploaded. Add an instruction or press Send to analyze it.");
      els.input.focus();
      resizeInput();
    } catch (error) {
      clearUploadedDocument();
      toast(error.message, "error");
    } finally {
      state.uploading = false;
      $("#uploadButton").disabled = false;
    }
  }

  function resizeInput() {
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, 150)}px`;
    els.send.disabled = state.busy || (!els.input.value.trim() && !state.uploadedDocument);
  }

  function closeSidebarOnMobile() {
    if (window.innerWidth <= 760) els.sidebar.classList.remove("open");
  }

  // Events
  $("#newChatButton").addEventListener("click", createThread);
  $("#refreshThreads").addEventListener("click", loadThreads);
  $("#sendButton").addEventListener("click", () => sendMessage());
  els.input.addEventListener("input", resizeInput);
  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  document.querySelectorAll(".suggestion-card").forEach((button) => {
    button.addEventListener("click", () => sendMessage(button.dataset.prompt));
  });
  $("#uploadButton").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) uploadDocument(file);
  });
  $("#removeAttachedFile").addEventListener("click", clearUploadedDocument);
  $("#settingsButton").addEventListener("click", () => {
    els.apiInput.value = state.apiBase;
    els.settingsModal.showModal();
  });
  $("#saveSettingsButton").addEventListener("click", (event) => {
    event.preventDefault();
    const value = els.apiInput.value.trim().replace(/\/$/, "");
    if (!/^https?:\/\//i.test(value)) return toast("Enter a valid http:// or https:// API URL.", "error");
    state.apiBase = value;
    localStorage.setItem("domAiApiBase", value);
    els.settingsModal.close();
    state.threadId = null;
    resetChatView();
    loadThreads().then(() => toast("API settings saved."));
  });
  $("#openSidebar").addEventListener("click", () => els.sidebar.classList.add("open"));
  $("#closeSidebar").addEventListener("click", closeSidebarOnMobile);

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      createThread();
    }
    if (event.key === "Escape") els.sidebar.classList.remove("open");
  });

  // Start with the conversation list. The user can begin a new chat from the welcome screen.
  loadThreads();
})();
