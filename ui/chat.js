const playlistSelect = document.getElementById(
    "playlistSelect"
);

const videoSelect = document.getElementById(
    "videoSelect"
);

const refreshVideosBtn = document.getElementById(
    "refreshVideosBtn"
);

const removePlaylistBtn = document.getElementById(
    "removePlaylistBtn"
);

const removeVideoBtn = document.getElementById(
    "removeVideoBtn"
);

const currentVideoTitle = document.getElementById(
    "currentVideoTitle"
);

const scopeBadge = document.getElementById(
    "scopeBadge"
);

const searchAllToggle = document.getElementById(
    "searchAllToggle"
);

const themeToggleBtn = document.getElementById(
    "themeToggleBtn"
);

const chatForm = document.getElementById(
    "chatForm"
);

const chatInput = document.getElementById(
    "chatInput"
);

const sendChatBtn = document.getElementById(
    "sendChatBtn"
);

const sendChatText = document.getElementById(
    "sendChatText"
);

const chatLoader = document.getElementById(
    "chatLoader"
);

const chatMessages = document.getElementById(
    "chatMessages"
);

const chatEmptyState = document.getElementById(
    "chatEmptyState"
);

const clearChatBtn = document.getElementById(
    "clearChatBtn"
);

const chatStatus = document.getElementById(
    "chatStatus"
);


let player = null;
let playerReady = false;

let allVideos = [];
let playlistsMap = {};
let selectedPlaylistId = null;
let videos = [];

let chatHistory = [];


/* ============================================================
   HELPERS & SCOPE
   ============================================================ */

function updateScopeBadge() {
    if (!scopeBadge) return;

    if (searchAllToggle && searchAllToggle.checked) {
        scopeBadge.textContent = "All Playlists";
        scopeBadge.className = "scope-badge global";
    } else if (selectedPlaylistId === "_standalone_" || (!getCurrentPlaylistId() && getSelectedVideo())) {
        scopeBadge.textContent = "Selected Video";
        scopeBadge.className = "scope-badge";
    } else {
        scopeBadge.textContent = "Selected Playlist";
        scopeBadge.className = "scope-badge";
    }
}

if (searchAllToggle) {
    searchAllToggle.addEventListener("change", updateScopeBadge);
}

function getSelectedVideo() {
    return (
        videos.find(
            video =>
                video.video_id ===
                videoSelect.value
        ) || null
    );
}


function getScope() {
    if (
        searchAllToggle &&
        searchAllToggle.checked
    ) {
        return "all";
    }

    if (selectedPlaylistId === "_standalone_" || (!getCurrentPlaylistId() && getSelectedVideo())) {
        return "video";
    }

    return "playlist";
}


function getVideoTitle(videoId) {
    const video =
        allVideos.find(
            item =>
                item.video_id ===
                videoId
        ) ||
        videos.find(
            item =>
                item.video_id ===
                videoId
        );

    return video
        ? video.title
        : videoId || "Unknown video";
}


function getCurrentPlaylistId() {
    if (
        playlistSelect &&
        playlistSelect.value &&
        playlistSelect.value !== "_standalone_"
    ) {
        return playlistSelect.value;
    }

    if (
        selectedPlaylistId &&
        selectedPlaylistId !== "_standalone_"
    ) {
        return selectedPlaylistId;
    }

    const saved =
        localStorage.getItem(
            "youtubeReviserCurrentPlaylistId"
        );

    if (saved && saved !== "_standalone_") {
        return saved;
    }

    const selectedVideo =
        getSelectedVideo();

    return (
        selectedVideo &&
        selectedVideo.playlist_id
    )
        ? selectedVideo.playlist_id
        : null;
}


function scrollChatToBottom() {
    chatMessages.scrollTop =
        chatMessages.scrollHeight;
}


/* ============================================================
   LOADING
   ============================================================ */

function setChatLoading(loading) {
    sendChatBtn.disabled = loading;
    chatInput.disabled = loading;

    if (loading) {
        sendChatText.textContent =
            "Thinking...";

        chatLoader.classList.remove(
            "hidden"
        );
    } else {
        sendChatText.textContent =
            "Send";

        chatLoader.classList.add(
            "hidden"
        );

        chatInput.focus();
    }
}


/* ============================================================
   CHAT RENDERING & MARKDOWN
   ============================================================ */

function formatMarkdown(text) {
    if (!text) return "";
    let safe = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Code blocks
    safe = safe.replace(/```([\s\S]*?)```/g, (m, code) => {
        return `<pre class="chat-code-block"><code>${code.trim()}</code></pre>`;
    });

    // Inline code
    safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Bold
    safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

    // Italic
    safe = safe.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");

    return safe;
}


function createAssistantStreamingBubble() {
    chatEmptyState.classList.add("hidden");

    const message = document.createElement("div");
    message.className = "chat-message assistant";

    const label = document.createElement("div");
    label.className = "chat-message-label";
    label.textContent = "YouTube Reviser";

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble streaming";

    message.appendChild(label);
    message.appendChild(bubble);
    chatMessages.appendChild(message);
    scrollChatToBottom();

    return { messageEl: message, bubbleEl: bubble };
}


function appendChatBubble(
    role,
    content
) {
    chatEmptyState.classList.add(
        "hidden"
    );

    const message =
        document.createElement("div");

    message.className =
        `chat-message ${role}`;

    const label =
        document.createElement("div");

    label.className =
        "chat-message-label";

    label.textContent =
        role === "user"
            ? "You"
            : "YouTube Reviser";

    const bubble =
        document.createElement("div");

    bubble.className =
        "chat-bubble";

    if (role === "user") {
        bubble.textContent = content;
    } else {
        bubble.innerHTML = formatMarkdown(content);
    }

    message.appendChild(label);
    message.appendChild(bubble);

    chatMessages.appendChild(
        message
    );

    scrollChatToBottom();
}


function appendError(message) {
    chatEmptyState.classList.add(
        "hidden"
    );

    const error =
        document.createElement("div");

    error.className =
        "chat-error";

    error.textContent =
        message;

    chatMessages.appendChild(
        error
    );

    scrollChatToBottom();
}


/* ============================================================
   TIMESTAMP
   ============================================================ */

function timestampToSeconds(
    timestamp
) {
    if (!timestamp) {
        return 0;
    }

    const parts =
        timestamp
            .trim()
            .split(":")
            .map(Number);

    if (
        parts.some(
            value =>
                Number.isNaN(value)
        )
    ) {
        return 0;
    }

    if (parts.length === 2) {
        return (
            parts[0] * 60 +
            parts[1]
        );
    }

    if (parts.length === 3) {
        return (
            parts[0] * 3600 +
            parts[1] * 60 +
            parts[2]
        );
    }

    return Number.isFinite(parts[0])
        ? parts[0]
        : 0;
}


/* ============================================================
   YOUTUBE PLAYER
   ============================================================ */

function seekToTimestamp(
    videoId,
    timestamp,
    url
) {
    if (!videoId && url) {
        try {
            const parsed = new URL(url);
            videoId = parsed.searchParams.get("v");
        } catch (e) {}
    }

    const seconds =
        timestampToSeconds(
            timestamp
        );

    if (videoId) {
        // Find which playlist this video belongs to
        const foundVideo = allVideos.find(v => v.video_id === videoId);
        if (foundVideo) {
            const targetPlaylistId = foundVideo.playlist_id || "_standalone_";
            if (targetPlaylistId !== selectedPlaylistId && playlistsMap[targetPlaylistId]) {
                if (playlistSelect) {
                    playlistSelect.value = targetPlaylistId;
                }
                populateVideosForPlaylist(targetPlaylistId, videoId);
            }
        }

        if (videoSelect) {
            const hasOption = Array.from(videoSelect.options).some(
                opt => opt.value === videoId
            );
            if (hasOption) {
                videoSelect.value = videoId;
            }
        }

        if (currentVideoTitle) {
            currentVideoTitle.textContent =
                getVideoTitle(videoId);
        }

        localStorage.setItem(
            "youtubeReviserCurrentVideoId",
            videoId
        );

        loadPlayerVideo(
            videoId,
            seconds
        );
    }
}


function renderTimestampButton(
    result,
    container
) {
    const button =
        document.createElement(
            "button"
        );

    button.type =
        "button";

    button.className =
        "timestamp-button";

    const rawTime =
        result.timestamp ||
        "00:00";

    button.textContent =
        rawTime.startsWith("▶")
            ? rawTime
            : `▶ ${rawTime}`;

    button.title =
        `Play at ${rawTime}`;

    button.addEventListener(
        "click",
        (e) => {
            e.preventDefault();
            e.stopPropagation();
            seekToTimestamp(
                result.video_id,
                result.timestamp ||
                    "00:00",
                result.url
            );
        }
    );

    container.appendChild(
        button
    );
}


/* ============================================================
   CASUAL QUERIES & SOURCES HELPERS
   ============================================================ */

const CASUAL_QUERIES = new Set([
    "hello", "hi", "hey", "hii", "heyy", "hlo", "hola",
    "thanks", "thank you", "thank u", "thx", "dhanyawad", "shukriya",
    "good morning", "good evening", "good afternoon", "good night",
    "namaste", "pranam", "kaise ho", "how are you", "who are you",
    "kya haal hai", "ok", "okay", "bye", "goodbye", "help",
    "thank", "welcome"
]);

function isCasualQuery(query) {
    if (!query) return false;
    const clean = query
        .toLowerCase()
        .trim()
        .replace(/[?!.,;:~]/g, "")
        .trim();
    return CASUAL_QUERIES.has(clean);
}


function sortSourcesByVideoChronological(sources) {
    if (!Array.isArray(sources) || sources.length === 0) {
        return [];
    }

    // Group items by video_id while preserving the order of video appearance
    const videoGroups = new Map();
    for (const item of sources) {
        const vid = item.video_id || "unknown";
        if (!videoGroups.has(vid)) {
            videoGroups.set(vid, []);
        }
        videoGroups.get(vid).push(item);
    }

    const sorted = [];
    for (const [, group] of videoGroups) {
        // Sort chronologically within the same video
        group.sort((a, b) => {
            const timeA =
                a.start_sec !== undefined
                    ? Number(a.start_sec)
                    : a.start_time !== undefined
                    ? Number(a.start_time)
                    : timestampToSeconds(a.timestamp);

            const timeB =
                b.start_sec !== undefined
                    ? Number(b.start_sec)
                    : b.start_time !== undefined
                    ? Number(b.start_time)
                    : timestampToSeconds(b.timestamp);

            return timeA - timeB;
        });
        sorted.push(...group);
    }

    return sorted;
}


/* ============================================================
   SOURCES FOR NORMAL CHAT
   ============================================================ */

function renderSources(
    sources
) {
    if (
        !Array.isArray(sources) ||
        sources.length === 0
    ) {
        return;
    }

    const sortedSources =
        sortSourcesByVideoChronological(
            sources
        );

    const wrapper =
        document.createElement("div");

    wrapper.className =
        "chat-sources";

    const heading =
        document.createElement("div");

    heading.className =
        "chat-sources-heading";

    heading.textContent =
        "Relevant timestamps";

    const buttons =
        document.createElement("div");

    buttons.className =
        "timestamp-buttons";

    sortedSources
        .slice(0, 5)
        .forEach(
            source => {
                renderTimestampButton(
                    source,
                    buttons
                );
            }
        );

    wrapper.appendChild(
        heading
    );

    wrapper.appendChild(
        buttons
    );

    chatMessages.appendChild(
        wrapper
    );

    scrollChatToBottom();
}


/* ============================================================
   LOCATE RESULTS
   ============================================================ */

function renderLocateResults(
    response
) {
    chatEmptyState.classList.add(
        "hidden"
    );

    const results =
        Array.isArray(
            response?.results
        )
            ? response.results
            : [];

    const block =
        document.createElement("div");

    block.className =
        "locate-results";

    /* --------------------------------------------------------
       TOPIC NOT FOUND
       -------------------------------------------------------- */

    if (results.length === 0) {

        const empty =
            document.createElement(
                "div"
            );

        empty.className =
            "locate-empty";

        empty.textContent =
            response?.message ||
            "Bhai, ye topic is playlist mein cover nahi hua hai. Agar chaho to main tumhe ye topic yahin padha sakta hoon.";

        block.appendChild(
            empty
        );

        chatMessages.appendChild(
            block
        );

        scrollChatToBottom();

        return;
    }


    /* --------------------------------------------------------
       TOPIC FOUND
       -------------------------------------------------------- */

    const heading =
        document.createElement(
            "div"
        );

    heading.className =
        "locate-heading";

    heading.textContent =
        "Relevant timestamps:";

    block.appendChild(
        heading
    );


    results
        .slice(0, 5)
        .forEach(
            (result, index) => {

                const item =
                    document.createElement(
                        "button"
                    );

                item.type =
                    "button";

                item.className =
                    "locate-result";

                item.title =
                    `Play Video at ${result.timestamp || "00:00"}`;

                item.addEventListener(
                    "click",
                    (e) => {
                        e.preventDefault();
                        seekToTimestamp(
                            result.video_id,
                            result.timestamp ||
                                "00:00",
                            result.url
                        );
                    }
                );


                /* Result number */

                const number =
                    document.createElement(
                        "div"
                    );

                number.className =
                    "locate-result-number";

                number.textContent =
                    index + 1;


                /* Video Title Content */

                const content =
                    document.createElement(
                        "div"
                    );

                content.className =
                    "locate-result-content";

                const title =
                    document.createElement(
                        "div"
                    );

                title.className =
                    "locate-result-title";

                const videoNumber =
                    result.video_number;

                const videoTitle =
                    result.video_title ||
                    getVideoTitle(
                        result.video_id
                    );

                if (
                    videoNumber !== null &&
                    videoNumber !== undefined
                ) {
                    title.textContent =
                        `Video ${videoNumber} — ${videoTitle}`;
                } else {
                    title.textContent =
                        videoTitle;
                }

                content.appendChild(
                    title
                );


                /* Timestamp Span (▶ timestamp) */

                const timestamp =
                    document.createElement(
                        "span"
                    );

                timestamp.className =
                    "locate-result-timestamp";

                const rawTime =
                    result.timestamp ||
                    "00:00";

                timestamp.textContent =
                    rawTime.startsWith("▶")
                        ? rawTime
                        : `▶ ${rawTime}`;


                item.appendChild(
                    number
                );

                item.appendChild(
                    content
                );

                item.appendChild(
                    timestamp
                );

                block.appendChild(
                    item
                );
            }
        );


    chatMessages.appendChild(
        block
    );

    scrollChatToBottom();
}


/* ============================================================
   YOUTUBE PLAYER
   ============================================================ */

function loadPlayerVideo(
    videoId,
    startSeconds = 0
) {
    if (!videoId) {
        return;
    }

    if (
        playerReady &&
        player
    ) {
        player.loadVideoById(
            {
                videoId,
                startSeconds,
            }
        );

        return;
    }

    createPlayer(
        videoId,
        startSeconds
    );
}


function createPlayer(
    videoId,
    startSeconds = 0
) {
    if (
        typeof YT ===
        "undefined"
    ) {
        window.pendingVideoId =
            videoId;

        window.pendingStartSeconds =
            startSeconds;

        return;
    }

    if (player) {
        try {
            player.destroy();
        } catch {
            // Ignore player cleanup errors.
        }

        player = null;
        playerReady = false;
    }

    player =
        new YT.Player(
            "youtubePlayer",
            {
                videoId,

                playerVars: {
                    rel: 0,
                    modestbranding: 1,
                    playsinline: 1,
                },

                events: {
                    onReady: event => {
                        playerReady =
                            true;

                        if (
                            startSeconds > 0
                        ) {
                            event.target.seekTo(
                                startSeconds,
                                true
                            );

                            event.target.playVideo();
                        }
                    },

                    onError: () => {
                        chatStatus.textContent =
                            "Unable to load this YouTube video.";
                    },
                },
            }
        );
}


/* ============================================================
   PLAYLIST & VIDEO LOADING
   ============================================================ */

async function loadVideos() {
    refreshVideosBtn.disabled = true;

    try {
        const response = await fetch("/api/videos");

        if (!response.ok) {
            let message = "Unable to load indexed videos.";
            try {
                const data = await response.json();
                if (data.detail) {
                    message = data.detail;
                }
            } catch {
                // Ignore invalid response.
            }
            throw new Error(message);
        }

        const data = await response.json();
        const indexedVideos = Array.isArray(data.videos) ? data.videos : [];
        allVideos = indexedVideos;

        // Build playlists mapping from all indexed videos using playlist_id
        playlistsMap = {};
        allVideos.forEach(video => {
            const pId = video.playlist_id || "_standalone_";
            if (!playlistsMap[pId]) {
                const pTitle =
                    video.playlist_title ||
                    (pId === "_standalone_" ? "Individual Videos" : "YouTube Playlist");
                playlistsMap[pId] = {
                    id: pId,
                    title: pTitle,
                    videos: [],
                };
            }
            playlistsMap[pId].videos.push(video);
        });

        // Preserve video numbers and order inside each playlist
        Object.values(playlistsMap).forEach(p => {
            p.videos.sort((a, b) => {
                const numA = (a.video_number !== null && a.video_number !== undefined) ? a.video_number : 999999;
                const numB = (b.video_number !== null && b.video_number !== undefined) ? b.video_number : 999999;
                if (numA !== numB) return numA - numB;
                return (a.title || "").localeCompare(b.title || "");
            });
        });

        // Populate playlist dropdown
        playlistSelect.innerHTML = "";
        const playlistIds = Object.keys(playlistsMap);

        if (playlistIds.length === 0) {
            const pOption = document.createElement("option");
            pOption.value = "";
            pOption.textContent = "No indexed playlists found";
            playlistSelect.appendChild(pOption);

            videoSelect.innerHTML = "";
            const vOption = document.createElement("option");
            vOption.value = "";
            vOption.textContent = "No indexed videos found";
            videoSelect.appendChild(vOption);

            currentVideoTitle.textContent = "No videos available";
            chatStatus.textContent = "Process at least one video before starting a chat.";
            videos = [];
            selectedPlaylistId = null;
            updateRemovePlaylistVisibility();
            updateScopeBadge();
            return;
        }

        playlistIds.forEach(pId => {
            const p = playlistsMap[pId];
            const pOption = document.createElement("option");
            pOption.value = pId;
            pOption.textContent = `${p.title} (${p.videos.length} ${p.videos.length === 1 ? "video" : "videos"})`;
            playlistSelect.appendChild(pOption);
        });

        // Determine which playlist to select
        const savedPlaylistId = localStorage.getItem("youtubeReviserCurrentPlaylistId");
        if (savedPlaylistId && playlistsMap[savedPlaylistId]) {
            selectedPlaylistId = savedPlaylistId;
        } else {
            selectedPlaylistId = playlistIds[0];
        }
        playlistSelect.value = selectedPlaylistId;

        const savedVideoId = localStorage.getItem("youtubeReviserCurrentVideoId");
        populateVideosForPlaylist(selectedPlaylistId, savedVideoId);

    } catch (error) {
        playlistSelect.innerHTML = "";
        const pOption = document.createElement("option");
        pOption.value = "";
        pOption.textContent = "Unable to load playlists";
        playlistSelect.appendChild(pOption);

        videoSelect.innerHTML = "";
        const vOption = document.createElement("option");
        vOption.value = "";
        vOption.textContent = "Unable to load videos";
        videoSelect.appendChild(vOption);

        currentVideoTitle.textContent = "Unable to load videos";
        chatStatus.textContent = error.message || "Unable to load indexed videos.";
        videos = [];
        selectedPlaylistId = null;
        updateRemovePlaylistVisibility();
        updateScopeBadge();
    } finally {
        refreshVideosBtn.disabled = false;
    }
}


/* ============================================================
   POPULATE VIDEOS FOR SELECTED PLAYLIST
   ============================================================ */

function populateVideosForPlaylist(playlistId, preferredVideoId = null) {
    selectedPlaylistId = playlistId;
    if (playlistId && playlistId !== "_standalone_") {
        localStorage.setItem("youtubeReviserCurrentPlaylistId", playlistId);
    }

    const currentPlaylist = playlistsMap[playlistId];
    videos = currentPlaylist ? currentPlaylist.videos : [];

    videoSelect.innerHTML = "";

    if (videos.length === 0) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No videos in this playlist";
        videoSelect.appendChild(option);
        currentVideoTitle.textContent = "No videos in this playlist";
        updateRemovePlaylistVisibility();
        updateScopeBadge();
        return;
    }

    videos.forEach(video => {
        const option = document.createElement("option");
        option.value = video.video_id;

        const videoNumber = video.video_number;
        const title = video.title || video.video_id;

        if (videoNumber !== null && videoNumber !== undefined) {
            option.textContent = `Video ${videoNumber} — ${title}`;
        } else {
            option.textContent = title;
        }

        videoSelect.appendChild(option);
    });

    let targetVideoId = null;
    if (preferredVideoId && videos.some(v => v.video_id === preferredVideoId)) {
        targetVideoId = preferredVideoId;
    } else {
        const savedVideoId = localStorage.getItem("youtubeReviserCurrentVideoId");
        if (savedVideoId && videos.some(v => v.video_id === savedVideoId)) {
            targetVideoId = savedVideoId;
        } else {
            targetVideoId = videos[0].video_id;
        }
    }

    videoSelect.value = targetVideoId;
    handleVideoSelection();
}


/* ============================================================
   REMOVE BUTTONS VISIBILITY
   ============================================================ */

function updateRemoveButtonsVisibility() {
    if (removePlaylistBtn) {
        if (selectedPlaylistId && selectedPlaylistId !== "_standalone_") {
            removePlaylistBtn.classList.remove("hidden");
        } else {
            removePlaylistBtn.classList.add("hidden");
        }
    }

    if (removeVideoBtn) {
        const video = getSelectedVideo();
        if (video && video.video_id) {
            removeVideoBtn.classList.remove("hidden");
        } else {
            removeVideoBtn.classList.add("hidden");
        }
    }
}

function updateRemovePlaylistVisibility() {
    updateRemoveButtonsVisibility();
}


/* ============================================================
   VIDEO SELECTION
   ============================================================ */

function handleVideoSelection() {
    const video = getSelectedVideo();

    if (!video) {
        updateRemovePlaylistVisibility();
        return;
    }

    currentVideoTitle.textContent = video.title || video.video_id;
    localStorage.setItem("youtubeReviserCurrentVideoId", video.video_id);

    if (video.playlist_id) {
        selectedPlaylistId = video.playlist_id;
        localStorage.setItem("youtubeReviserCurrentPlaylistId", video.playlist_id);
    }

    loadPlayerVideo(video.video_id);
    updateRemovePlaylistVisibility();
    updateScopeBadge();
}


/* ============================================================
   CHAT API
   ============================================================ */

async function sendChat(
    question
) {

    const scope =
        getScope();

    const playlistId =
        getCurrentPlaylistId();

    const selectedVideo =
        getSelectedVideo();

    if (
        scope === "playlist" &&
        !playlistId
    ) {
        if (!allVideos || allVideos.length === 0) {
            throw new Error(
                "No indexed playlists found. Please process a playlist or video first."
            );
        }
    }


    const response =
        await fetch(
            "/api/chat",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body: JSON.stringify(
                    {
                        question,

                        chat_history:
                            chatHistory,

                        video_id:
                            selectedVideo
                                ? selectedVideo.video_id
                                : null,

                        playlist_id:
                            playlistId || null,

                        scope,
                    }
                ),
            }
        );


    if (!response.ok) {

        let message =
            "Unable to get an answer.";

        try {

            const data =
                await response.json();

            if (data.detail) {
                message =
                    data.detail;
            }

        } catch {
            // Ignore invalid error payload.
        }

        throw new Error(
            message
        );
    }

    return response.json();
}


/* ============================================================
   CHAT SUBMIT
   ============================================================ */

chatForm.addEventListener(
    "submit",
    async event => {

        event.preventDefault();

        const question =
            chatInput.value.trim();

        if (!question) {
            return;
        }

        /* --------------------------------------------
           User message
           -------------------------------------------- */

        appendChatBubble(
            "user",
            question
        );

        /* --------------------------------------------
           Add to history
           -------------------------------------------- */

        chatHistory.push(
            {
                role: "user",
                content: question,
            }
        );

        chatInput.value = "";
        chatStatus.textContent = isCasualQuery(question)
            ? ""
            : "Thinking...";

        setChatLoading(true);

        const scope = getScope();
        const playlistId = getCurrentPlaylistId();
        const selectedVideo = getSelectedVideo();

        let streamBubble = null;
        let accumulatedText = "";
        let locateModeHandled = false;

        try {
            const response = await fetch("/api/chat/stream", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    question,
                    chat_history: chatHistory.slice(0, -1),
                    video_id: selectedVideo ? selectedVideo.video_id : null,
                    playlist_id: playlistId || null,
                    scope,
                }),
            });

            if (!response.ok) {
                let message = "Unable to get an answer.";
                try {
                    const data = await response.json();
                    if (data.detail) {
                        message = data.detail;
                    }
                } catch {
                    // Ignore error parse
                }
                throw new Error(message);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n\n");
                buffer = lines.pop();

                for (const block of lines) {
                    const trimmed = block.trim();
                    if (!trimmed.startsWith("data:")) continue;
                    const dataStr = trimmed.slice(5).trim();
                    if (!dataStr) continue;

                    let evt;
                    try {
                        evt = JSON.parse(dataStr);
                    } catch {
                        continue;
                    }

                    if (evt.type === "start") {
                        chatStatus.textContent = "";
                        if (!streamBubble) {
                            streamBubble = createAssistantStreamingBubble();
                        }
                    } else if (evt.type === "token") {
                        chatStatus.textContent = "";
                        if (!streamBubble) {
                            streamBubble = createAssistantStreamingBubble();
                        }
                        accumulatedText += evt.token || "";
                        streamBubble.bubbleEl.innerHTML = formatMarkdown(accumulatedText);
                        scrollChatToBottom();
                    } else if (evt.type === "locate") {
                        locateModeHandled = true;
                        chatStatus.textContent = "";
                        if (streamBubble && streamBubble.messageEl) {
                            streamBubble.messageEl.remove();
                            streamBubble = null;
                        }
                        renderLocateResults(evt);

                        const historyText = evt.results && evt.results.length
                            ? evt.results
                                .slice(0, 5)
                                .map(result => {
                                    const number = result.video_number !== null && result.video_number !== undefined
                                        ? `Video ${result.video_number} — `
                                        : "";
                                    return (
                                        `${number}` +
                                        `${result.video_title || getVideoTitle(result.video_id)} ` +
                                        `at ${result.timestamp}`
                                    );
                                })
                                .join("; ")
                            : (
                                evt.message ||
                                "This topic is not covered in the indexed videos."
                            );

                        chatHistory.push({
                            role: "assistant",
                            content: historyText,
                        });
                    } else if (evt.type === "done") {
                        chatStatus.textContent = "";
                        if (streamBubble && streamBubble.bubbleEl) {
                            streamBubble.bubbleEl.classList.remove("streaming");
                            streamBubble.bubbleEl.innerHTML = formatMarkdown(accumulatedText);
                        }
                        if (!locateModeHandled) {
                            if (!isCasualQuery(question) && Array.isArray(evt.sources) && evt.sources.length > 0) {
                                renderSources(evt.sources);
                            }
                            chatHistory.push({
                                role: "assistant",
                                content: accumulatedText,
                            });
                        }
                    } else if (evt.type === "error") {
                        throw new Error(evt.message || "Failed to generate answer.");
                    }
                }
            }

        } catch (error) {
            chatStatus.textContent = "";
            chatHistory.pop();
            if (streamBubble && streamBubble.messageEl) {
                streamBubble.messageEl.remove();
            }
            appendError(
                error.message ||
                "Something went wrong while contacting the assistant."
            );
        } finally {
            setChatLoading(false);
        }
    }
);


/* ============================================================
   EVENTS
   ============================================================ */

if (playlistSelect) {
    playlistSelect.addEventListener("change", () => {
        const pId = playlistSelect.value;
        if (pId && playlistsMap[pId]) {
            populateVideosForPlaylist(pId);
        }
        updateScopeBadge();
    });
}

videoSelect.addEventListener(
    "change",
    handleVideoSelection
);


refreshVideosBtn.addEventListener(
    "click",
    loadVideos
);


if (removeVideoBtn) {
    removeVideoBtn.addEventListener(
        "click",
        async () => {
            const video = getSelectedVideo();
            if (!video || !video.video_id) {
                alert("No video selected to remove.");
                return;
            }

            const videoLabel = video.title || video.video_id;
            const confirmed = window.confirm(
                `Remove video "${videoLabel}" from knowledge base?`
            );

            if (!confirmed) {
                return;
            }

            removeVideoBtn.disabled = true;
            removeVideoBtn.textContent = "Removing video...";
            chatStatus.textContent = "Removing video from knowledge base...";

            try {
                const response = await fetch(
                    `/api/video/${encodeURIComponent(video.video_id)}`,
                    {
                        method: "DELETE",
                    }
                );

                if (!response.ok) {
                    let message = "Unable to remove video.";
                    try {
                        const data = await response.json();
                        if (data.detail) {
                            message = data.detail;
                        }
                    } catch {
                        // Ignore error parse
                    }
                    throw new Error(message);
                }

                localStorage.removeItem("youtubeReviserCurrentVideoId");
                chatStatus.textContent = "Video removed from knowledge base.";

                if (player && typeof player.stopVideo === "function") {
                    try {
                        player.stopVideo();
                    } catch {
                        // ignore player errors
                    }
                }

                await loadVideos();

            } catch (error) {
                chatStatus.textContent = error.message || "Failed to remove video.";
                alert(`Error: ${error.message || "Failed to remove video."}`);
            } finally {
                removeVideoBtn.disabled = false;
                removeVideoBtn.textContent = "🗑 Remove Video";
            }
        }
    );
}


if (removePlaylistBtn) {
    removePlaylistBtn.addEventListener(
        "click",
        async () => {
            if (!selectedPlaylistId || selectedPlaylistId === "_standalone_") {
                alert("No active playlist selected to remove.");
                return;
            }

            const confirmed = window.confirm(
                "Remove this playlist and all its indexed videos?"
            );

            if (!confirmed) {
                return;
            }

            removePlaylistBtn.disabled = true;
            removePlaylistBtn.textContent = "Removing playlist...";
            chatStatus.textContent = "Removing playlist from knowledge base...";

            try {
                const response = await fetch(
                    `/api/playlist/${encodeURIComponent(selectedPlaylistId)}`,
                    {
                        method: "DELETE",
                    }
                );

                if (!response.ok) {
                    let message = "Unable to remove playlist.";
                    try {
                        const data = await response.json();
                        if (data.detail) {
                            message = data.detail;
                        }
                    } catch {
                        // Ignore error parse
                    }
                    throw new Error(message);
                }

                // Clear playlist state from localStorage
                localStorage.removeItem("youtubeReviserCurrentPlaylistId");
                localStorage.removeItem("youtubeReviserCurrentVideoId");
                localStorage.removeItem("youtubeReviserCurrentVideos");
                localStorage.removeItem("youtubeReviserCurrentTitle");

                chatStatus.textContent = "Playlist removed from knowledge base.";

                // Stop player
                if (player && typeof player.stopVideo === "function") {
                    try {
                        player.stopVideo();
                    } catch {
                        // ignore player errors
                    }
                }

                // Clear chat
                chatHistory = [];
                chatMessages.innerHTML = "";
                chatMessages.appendChild(chatEmptyState);
                chatEmptyState.classList.remove("hidden");

                // Reload videos and update playlist list
                await loadVideos();

            } catch (error) {
                chatStatus.textContent = error.message || "Failed to remove playlist.";
                alert(`Error: ${error.message || "Failed to remove playlist."}`);
            } finally {
                removePlaylistBtn.disabled = false;
                removePlaylistBtn.textContent = "🗑 Remove Playlist";
            }
        }
    );
}


clearChatBtn.addEventListener(
    "click",
    () => {

        chatHistory = [];

        chatMessages.innerHTML =
            "";

        chatMessages.appendChild(
            chatEmptyState
        );

        chatEmptyState.classList.remove(
            "hidden"
        );

        chatStatus.textContent =
            "";

        chatInput.focus();
    }
);


chatInput.addEventListener(
    "keydown",
    event => {

        if (
            event.key ===
                "Enter" &&
            !event.shiftKey
        ) {

            event.preventDefault();

            chatForm.requestSubmit();
        }
    }
);


/* ============================================================
   YOUTUBE IFRAME API
   ============================================================ */

window.onYouTubeIframeAPIReady =
    () => {

        const pendingVideoId =
            window.pendingVideoId;

        if (pendingVideoId) {

            createPlayer(
                pendingVideoId,
                window.pendingStartSeconds ||
                    0
            );

            window.pendingVideoId =
                null;

            window.pendingStartSeconds =
                0;
        }
    };


const youtubeApiScript =
    document.createElement(
        "script"
    );

youtubeApiScript.src =
    "https://www.youtube.com/iframe_api";

document.head.appendChild(
    youtubeApiScript
);


/* ============================================================
   INITIAL LOAD
   ============================================================ */

loadVideos();