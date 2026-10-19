const urlForm = document.getElementById(
    "urlForm"
);

const youtubeUrl = document.getElementById(
    "youtubeUrl"
);

const analyzeBtn = document.getElementById(
    "analyzeBtn"
);

const analyzeLoader = document.getElementById(
    "analyzeLoader"
);

const analyzeBtnText =
    analyzeBtn.querySelector(
        ".btn-text"
    );

const clearBtn = document.getElementById(
    "clearBtn"
);

const analysisSection =
    document.getElementById(
        "analysisSection"
    );

const progressSection =
    document.getElementById(
        "progressSection"
    );

const messageSection =
    document.getElementById(
        "messageSection"
    );

const messageBox =
    document.getElementById(
        "messageBox"
    );

const messageIcon =
    document.getElementById(
        "messageIcon"
    );

const messageTitle =
    document.getElementById(
        "messageTitle"
    );

const messageText =
    document.getElementById(
        "messageText"
    );

const closeMessageBtn =
    document.getElementById(
        "closeMessageBtn"
    );

const contentTypeBadge =
    document.getElementById(
        "contentTypeBadge"
    );

const contentTitle =
    document.getElementById(
        "contentTitle"
    );

const contentUrl =
    document.getElementById(
        "contentUrl"
    );

const typeValue =
    document.getElementById(
        "typeValue"
    );

const videoCount =
    document.getElementById(
        "videoCount"
    );

const savedCount =
    document.getElementById(
        "savedCount"
    );

const newCount =
    document.getElementById(
        "newCount"
    );

const videoList =
    document.getElementById(
        "videoList"
    );

const listStatus =
    document.getElementById(
        "listStatus"
    );

const processBtn =
    document.getElementById(
        "processBtn"
    );

const removePlaylistBtn =
    document.getElementById(
        "removePlaylistBtn"
    );

const themeToggleBtn =
    document.getElementById(
        "themeToggleBtn"
    );

const progressMainHeading =
    document.getElementById(
        "progressMainHeading"
    );

const progressStepText =
    document.getElementById(
        "progressStepText"
    );

const progressLabel =
    document.getElementById(
        "progressLabel"
    );

const progressPercent =
    document.getElementById(
        "progressPercent"
    );

const progressFill =
    document.getElementById(
        "progressFill"
    );

const completionSummary =
    document.getElementById(
        "completionSummary"
    );

const completionDetails =
    document.getElementById(
        "completionDetails"
    );

const processingList =
    document.getElementById(
        "processingList"
    );

const stageRowFetching =
    document.getElementById(
        "stageRowFetching"
    );

const stageIconFetching =
    document.getElementById(
        "stageIconFetching"
    );

const stageMetricFetching =
    document.getElementById(
        "stageMetricFetching"
    );

const stageRowChunking =
    document.getElementById(
        "stageRowChunking"
    );

const stageIconChunking =
    document.getElementById(
        "stageIconChunking"
    );

const stageMetricChunking =
    document.getElementById(
        "stageMetricChunking"
    );

const stageRowEmbedding =
    document.getElementById(
        "stageRowEmbedding"
    );

const stageIconEmbedding =
    document.getElementById(
        "stageIconEmbedding"
    );

const stageMetricEmbedding =
    document.getElementById(
        "stageMetricEmbedding"
    );

const stageRowIndexing =
    document.getElementById(
        "stageRowIndexing"
    );

const stageIconIndexing =
    document.getElementById(
        "stageIconIndexing"
    );

const stageMetricIndexing =
    document.getElementById(
        "stageMetricIndexing"
    );


let currentAnalysis = null;


/* ============================================================
   URL HELPERS
   ============================================================ */

function isValidYouTubeUrl(
    value
) {
    try {
        const url =
            new URL(value);

        const hostname =
            url.hostname.toLowerCase();

        return (
            hostname ===
                "youtube.com" ||
            hostname ===
                "www.youtube.com" ||
            hostname ===
                "m.youtube.com" ||
            hostname ===
                "youtu.be" ||
            hostname ===
                "www.youtu.be"
        );

    } catch {
        return false;
    }
}


function detectUrlType(
    value
) {
    try {
        const url =
            new URL(value);

        /*
         * Any URL containing list= is a playlist,
         * even when v= is also present.
         * e.g. /watch?v=XYZ&list=ABC is a playlist.
         */
        if (
            url.searchParams.has(
                "list"
            ) &&
            url.searchParams.get(
                "list"
            )
        ) {
            return "playlist";
        }

        /*
         * A /watch?v=... URL without list= is
         * a single video.
         */
        if (
            url.searchParams.has(
                "v"
            ) &&
            url.searchParams.get(
                "v"
            )
        ) {
            return "video";
        }

        if (
            url.hostname.includes(
                "youtu.be"
            ) &&
            url.pathname.length > 1
        ) {
            return "video";
        }

        return "unknown";

    } catch {
        return "unknown";
    }
}


/* ============================================================
   ANALYZE BUTTON
   ============================================================ */

function setAnalyzeLoading(
    loading
) {
    analyzeBtn.disabled =
        loading;

    if (loading) {
        analyzeLoader.classList.remove(
            "hidden"
        );

        analyzeBtnText.textContent =
            "Analyzing...";

    } else {
        analyzeLoader.classList.add(
            "hidden"
        );

        analyzeBtnText.textContent =
            "Analyze URL";
    }
}


/* ============================================================
   MESSAGE
   ============================================================ */

function showMessage(
    type,
    title,
    text
) {
    messageSection.classList.remove(
        "hidden"
    );

    messageBox.classList.remove(
        "success",
        "error",
        "warning"
    );

    messageBox.classList.add(
        type
    );

    messageTitle.textContent =
        title;

    messageText.textContent =
        text;

    if (
        type ===
        "success"
    ) {
        messageIcon.textContent =
            "✓";
    } else {
        messageIcon.textContent =
            "!";
    }
}


function hideMessage() {
    messageSection.classList.add(
        "hidden"
    );
}


/* ============================================================
   ANALYSIS HELPERS
   ============================================================ */

function hideAnalysis() {
    analysisSection.classList.add(
        "hidden"
    );

    progressSection.classList.add(
        "hidden"
    );

    currentAnalysis =
        null;
}


function updateStats(
    data
) {
    const total =
        Number(
            data.total_videos || 0
        );

    const saved =
        Number(
            data.saved_videos || 0
        );

    const fresh =
        Number(
            data.new_videos ??
            Math.max(
                total - saved,
                0
            )
        );

    videoCount.textContent =
        total;

    savedCount.textContent =
        saved;

    newCount.textContent =
        fresh;

    typeValue.textContent =
        data.type ===
        "playlist"
            ? "Playlist"
            : "Video";
}


function updateHeader(
    data
) {
    contentTypeBadge.textContent =
        data.type ===
        "playlist"
            ? "PLAYLIST"
            : "VIDEO";

    contentTitle.textContent =
        data.title ||
        (
            data.type ===
            "playlist"
                ? "YouTube Playlist"
                : "YouTube Video"
        );

    contentUrl.textContent =
        data.url ||
        youtubeUrl.value;
}


/* ============================================================
   VIDEO LIST
   ============================================================ */

function renderVideos(
    videos
) {
    videoList.innerHTML =
        "";

    if (
        !videos ||
        videos.length === 0
    ) {
        listStatus.textContent =
            "0 videos";

        return;
    }

    listStatus.textContent =
        `${videos.length} ${
            videos.length === 1
                ? "video"
                : "videos"
        }`;

    videos.forEach(
        (
            video,
            index
        ) => {

            const item =
                document.createElement(
                    "div"
                );

            item.className =
                "video-item";


            const number =
                document.createElement(
                    "div"
                );

            number.className =
                "video-number";

            number.textContent =
                video.video_number ||
                index + 1;


            const info =
                document.createElement(
                    "div"
                );

            info.className =
                "video-info";


            const title =
                document.createElement(
                    "div"
                );

            title.className =
                "video-title";

            title.textContent =
                video.title ||
                "Untitled video";


            const id =
                document.createElement(
                    "div"
                );

            id.className =
                "video-id";

            id.textContent =
                video.video_id ||
                "";


            info.appendChild(
                title
            );

            info.appendChild(
                id
            );


            const status =
                document.createElement(
                    "span"
                );

            status.className =
                "status";


            if (
                video.already_saved
            ) {

                status.classList.add(
                    "saved"
                );

                status.textContent =
                    "ALREADY SAVED";

            } else {

                status.classList.add(
                    "new"
                );

                status.textContent =
                    "NEW";
            }


            item.appendChild(
                number
            );

            item.appendChild(
                info
            );

            item.appendChild(
                status
            );


            videoList.appendChild(
                item
            );
        }
    );
}


function updateProcessButton(
    data
) {
    const newVideos =
        Number(
            data.new_videos || 0
        );

    if (
        newVideos === 0
    ) {

        processBtn.disabled =
            true;

        processBtn.textContent =
            "Everything Already Saved";

    } else {

        processBtn.disabled =
            false;

        processBtn.textContent =
            `Process ${newVideos} ${
                newVideos === 1
                    ? "New Video"
                    : "New Videos"
            }`;
    }

    if (removePlaylistBtn) {
        if (
            data.type === "playlist" &&
            (
                Number(data.saved_videos || 0) > 0 ||
                data.playlist_id
            )
        ) {
            removePlaylistBtn.classList.remove(
                "hidden"
            );
        } else {
            removePlaylistBtn.classList.add(
                "hidden"
            );
        }
    }
}


/* ============================================================
   LOCAL STORAGE
   ============================================================ */

function saveCurrentAnalysis(
    data,
    fallbackUrl
) {
    try {

        localStorage.setItem(
            "youtubeReviserCurrentVideos",
            JSON.stringify(
                data.videos || []
            )
        );

        localStorage.setItem(
            "youtubeReviserCurrentUrl",
            data.url ||
                fallbackUrl ||
                ""
        );

        localStorage.setItem(
            "youtubeReviserCurrentTitle",
            data.title ||
                ""
        );

        /*
         * IMPORTANT:
         * Save the current playlist ID so chat.js
         * can restrict retrieval to this playlist.
         *
         * For a single video this becomes an empty string.
         */
        localStorage.setItem(
            "youtubeReviserCurrentPlaylistId",
            data.playlist_id ||
                ""
        );

    } catch {
        // localStorage is optional.
    }
}


/* ============================================================
   API — ANALYZE
   ============================================================ */

async function analyzeUrl(
    url
) {
    const response =
        await fetch(
            "/api/analyze",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body:
                    JSON.stringify(
                        {
                            url,
                        }
                    ),
            }
        );


    if (!response.ok) {

        let message =
            "Unable to analyze the URL.";

        try {

            const data =
                await response.json();

            if (
                data.detail
            ) {
                message =
                    data.detail;
            }

        } catch {
            // Ignore invalid error response.
        }

        throw new Error(
            message
        );
    }


    return response.json();
}


/* ============================================================
   API — PROCESS (STREAMING SSE PROGRESS)
   ============================================================ */

async function startProcessStream(
    url,
    videoIds,
    onEvent
) {
    const response =
        await fetch(
            "/api/process/stream",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json",
                },

                body:
                    JSON.stringify(
                        {
                            url,

                            video_ids:
                                videoIds,
                        }
                    ),
            }
        );

    if (!response.ok) {
        let message =
            "Unable to start video processing.";

        try {
            const data =
                await response.json();

            if (
                data.detail
            ) {
                message =
                    data.detail;
            }
        } catch {
            // Ignore invalid error response.
        }

        throw new Error(
            message
        );
    }

    const reader =
        response.body.getReader();
    const decoder =
        new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
        const { done, value } =
            await reader.read();
        if (done) break;

        buffer += decoder.decode(
            value,
            { stream: true }
        );
        const lines =
            buffer.split("\n\n");
        buffer = lines.pop();

        for (const block of lines) {
            const trimmed =
                block.trim();
            if (
                trimmed.startsWith("data: ")
            ) {
                try {
                    const data =
                        JSON.parse(
                            trimmed.slice(6)
                        );
                    onEvent(data);
                } catch (e) {
                    console.error("SSE parse error", e, block);
                }
            }
        }
    }
}


/* ============================================================
   PIPELINE STAGE STATE & PROGRESS
   ============================================================ */

let pipelineState = {
    totalVideos: 0,
    fetching: { status: "waiting", completed: 0, total: 0 },
    chunking: { status: "waiting", chunks: 0 },
    embedding: { status: "waiting", completed: 0, total: 0 },
    indexing: { status: "waiting", completed: 0, total: 0 },
    isComplete: false,
};

function resetPipelineStages(totalVideos) {
    pipelineState = {
        totalVideos: totalVideos || 0,
        fetching: { status: "processing", completed: 0, total: totalVideos || 0 },
        chunking: { status: "waiting", chunks: 0 },
        embedding: { status: "waiting", completed: 0, total: 0 },
        indexing: { status: "waiting", completed: 0, total: 0 },
        isComplete: false,
    };
    renderPipelineStages();
    updateOverallProgress();
}

function updatePipelineStage(stage, data) {
    if (!data) data = {};
    if (stage === "fetching") {
        if (data.status) pipelineState.fetching.status = data.status;
        if (data.completed !== undefined) pipelineState.fetching.completed = data.completed;
        if (data.total !== undefined) pipelineState.fetching.total = data.total;
    } else if (stage === "chunking") {
        if (data.status) pipelineState.chunking.status = data.status;
        if (data.chunks_count !== undefined) pipelineState.chunking.chunks = data.chunks_count;
        if (data.status === "processing" && pipelineState.fetching.status === "processing") {
            pipelineState.fetching.status = "success";
        }
    } else if (stage === "embedding") {
        if (data.status) pipelineState.embedding.status = data.status;
        if (data.completed !== undefined) pipelineState.embedding.completed = data.completed;
        if (data.total !== undefined) pipelineState.embedding.total = data.total;
        if (pipelineState.chunking.status !== "success") {
            pipelineState.chunking.status = "success";
        }
    } else if (stage === "indexing") {
        if (data.status) pipelineState.indexing.status = data.status;
        if (data.completed !== undefined) pipelineState.indexing.completed = data.completed;
        if (data.total !== undefined) pipelineState.indexing.total = data.total;
        if (pipelineState.embedding.status !== "success") {
            pipelineState.embedding.status = "success";
        }
    } else if (stage === "complete") {
        pipelineState.isComplete = true;
        pipelineState.fetching.status = "success";
        pipelineState.chunking.status = "success";
        pipelineState.embedding.status = "success";
        pipelineState.indexing.status = "success";
    }
    renderPipelineStages();
    updateOverallProgress();
}

function setStageVisual(rowEl, iconEl, metricEl, status, metricText) {
    if (!rowEl) return;
    rowEl.className = `pipeline-stage-item ${status || "waiting"}`;
    if (iconEl) {
        if (status === "success") {
            iconEl.textContent = "✓";
            iconEl.className = "stage-icon";
        } else if (status === "processing") {
            iconEl.textContent = "⟳";
            iconEl.className = "stage-icon spin";
        } else if (status === "failed") {
            iconEl.textContent = "✕";
            iconEl.className = "stage-icon";
        } else {
            iconEl.textContent = "○";
            iconEl.className = "stage-icon";
        }
    }
    if (metricEl && metricText !== undefined) {
        metricEl.textContent = metricText;
    }
}

function renderPipelineStages() {
    // 1. Fetching
    const fetchTotal = pipelineState.fetching.total || pipelineState.totalVideos || 0;
    const fetchMetric = `${pipelineState.fetching.completed} / ${fetchTotal}`;
    setStageVisual(stageRowFetching, stageIconFetching, stageMetricFetching, pipelineState.fetching.status, fetchMetric);

    // 2. Chunking
    let chunkMetric = "-";
    if (pipelineState.chunking.chunks > 0) {
        chunkMetric = `${pipelineState.chunking.chunks} chunks`;
    } else if (pipelineState.chunking.status === "processing") {
        chunkMetric = "Creating...";
    }
    setStageVisual(stageRowChunking, stageIconChunking, stageMetricChunking, pipelineState.chunking.status, chunkMetric);

    // 3. Embedding
    let embedMetric = "0 / 0";
    if (pipelineState.embedding.total > 0) {
        embedMetric = `${pipelineState.embedding.completed} / ${pipelineState.embedding.total}`;
    }
    setStageVisual(stageRowEmbedding, stageIconEmbedding, stageMetricEmbedding, pipelineState.embedding.status, embedMetric);

    // 4. Indexing
    let indexMetric = "0 / 0";
    if (pipelineState.indexing.total > 0) {
        indexMetric = `${pipelineState.indexing.completed} / ${pipelineState.indexing.total}`;
    }
    setStageVisual(stageRowIndexing, stageIconIndexing, stageMetricIndexing, pipelineState.indexing.status, indexMetric);
}

function updateOverallProgress() {
    if (pipelineState.isComplete) {
        setProgressDisplay(100);
        return;
    }

    let progress = 0;

    // Fetching transcripts: 0% to 40%
    const fetchTotal = pipelineState.fetching.total || pipelineState.totalVideos || 1;
    const fetchRatio = Math.min(1, Math.max(0, pipelineState.fetching.completed / fetchTotal));
    progress += fetchRatio * 40;

    // Creating chunks: 40% to 45% (5%)
    if (pipelineState.chunking.status === "success") {
        progress += 5;
    } else if (pipelineState.chunking.status === "processing") {
        progress += 2;
    }

    // Generating embeddings: 45% to 80% (35%)
    if (pipelineState.embedding.total > 0) {
        const embedRatio = Math.min(1, Math.max(0, pipelineState.embedding.completed / pipelineState.embedding.total));
        progress += embedRatio * 35;
    } else if (pipelineState.embedding.status === "success") {
        progress += 35;
    }

    // Saving to knowledge base: 80% to 100% (20%)
    if (pipelineState.indexing.total > 0) {
        const indexRatio = Math.min(1, Math.max(0, pipelineState.indexing.completed / pipelineState.indexing.total));
        progress += indexRatio * 20;
    } else if (pipelineState.indexing.status === "success") {
        progress += 20;
    }

    const calculatedPercent = Math.min(99, Math.round(progress));
    setProgressDisplay(calculatedPercent);
}

function setProgressDisplay(percent) {
    if (progressPercent) {
        progressPercent.textContent = `${percent}%`;
    }
    if (progressFill) {
        progressFill.style.width = `${percent}%`;
    }
    if (progressLabel) {
        const completed = pipelineState.fetching.completed || 0;
        const total = pipelineState.fetching.total || pipelineState.totalVideos || 0;
        progressLabel.textContent = `${completed} / ${total} videos completed`;
    }
}


/* ============================================================
   PROCESSING UI
   ============================================================ */

function showProcessingSection(
    total
) {
    progressSection.classList.remove(
        "hidden"
    );

    if (progressMainHeading) {
        progressMainHeading.textContent =
            "Processing your videos";
    }

    if (progressStepText) {
        progressStepText.textContent =
            "Fetching video transcripts...";
    }

    if (completionSummary) {
        completionSummary.classList.add(
            "hidden"
        );
    }

    processingList.innerHTML =
        "";

    resetPipelineStages(total);
}


function createProcessingItem(
    video,
    index
) {
    const item =
        document.createElement(
            "div"
        );

    item.className =
        "processing-item";
    item.dataset.videoId =
        video.video_id;


    const icon =
        document.createElement(
            "div"
        );

    icon.className =
        "processing-icon";

    icon.textContent =
        "○";


    const info =
        document.createElement(
            "div"
        );

    info.className =
        "processing-info";


    const title =
        document.createElement(
            "div"
        );

    title.className =
        "processing-title";

    const videoNum =
        video.video_number ||
        (index !== undefined ? index + 1 : null);
    const videoTitle =
        video.title ||
        video.video_id ||
        "Video";

    title.textContent =
        videoNum
            ? `Video ${videoNum} — ${videoTitle}`
            : videoTitle;


    const status =
        document.createElement(
            "div"
        );

    status.className =
        "processing-status waiting";

    status.textContent =
        "Waiting";


    info.appendChild(
        title
    );

    info.appendChild(
        status
    );


    item.appendChild(
        icon
    );

    item.appendChild(
        info
    );


    processingList.appendChild(
        item
    );


    return {
        item,
        icon,
        status,
        videoId: video.video_id,
    };
}


function markProcessingItem(
    item,
    state,
    message
) {
    if (!item) return;

    item.status.className =
        "processing-status";
    item.icon.className =
        "processing-icon";


    if (
        state ===
        "success"
    ) {
        item.icon.textContent =
            "✓";

        item.status.classList.add(
            "success"
        );

    } else if (
        state ===
        "failed"
    ) {
        item.icon.textContent =
            "✕";

        item.status.classList.add(
            "error"
        );

    } else if (
        state ===
        "processing"
    ) {
        item.icon.textContent =
            "⟳";

        item.icon.classList.add(
            "spin"
        );

        item.status.classList.add(
            "processing"
        );

    } else {
        item.icon.textContent =
            "○";

        item.status.classList.add(
            "waiting"
        );
    }

    item.status.textContent =
        message;
}


/* ============================================================
   NEW VIDEOS
   ============================================================ */

function getNewVideos() {

    if (
        !currentAnalysis
    ) {
        return [];
    }

    return (
        currentAnalysis.videos ||
        []
    ).filter(
        video =>
            !video.already_saved
    );
}


/* ============================================================
   ANALYZE FORM
   ============================================================ */

urlForm.addEventListener(
    "submit",
    async event => {

        event.preventDefault();

        hideMessage();


        const url =
            youtubeUrl.value.trim();


        if (!url) {

            showMessage(
                "error",
                "URL Required",
                "Please enter a YouTube video or playlist URL."
            );

            return;
        }


        if (
            !isValidYouTubeUrl(
                url
            )
        ) {

            showMessage(
                "error",
                "Invalid URL",
                "Please enter a valid YouTube URL."
            );

            return;
        }


        const urlType =
            detectUrlType(
                url
            );


        if (
            urlType ===
            "unknown"
        ) {

            showMessage(
                "error",
                "Unsupported URL",
                "Please enter a YouTube video or playlist URL."
            );

            return;
        }


        setAnalyzeLoading(
            true
        );


        try {

            const data =
                await analyzeUrl(
                    url
                );


            currentAnalysis =
                data;


            updateHeader(
                data
            );


            updateStats(
                data
            );


            renderVideos(
                data.videos ||
                    []
            );


            updateProcessButton(
                data
            );


            /*
             * Save playlist/video context for chat page.
             */
            saveCurrentAnalysis(
                data,
                url
            );


            analysisSection.classList.remove(
                "hidden"
            );


            progressSection.classList.add(
                "hidden"
            );


            const newVideos =
                Number(
                    data.new_videos ||
                    0
                );


            if (
                newVideos ===
                0
            ) {

                showMessage(
                    "success",
                    "Already Added",
                    "All videos from this URL are already in your knowledge base."
                );

            } else {

                showMessage(
                    "success",
                    "Ready to Ingest",
                    `${newVideos} new ${
                        newVideos === 1
                            ? "video is"
                            : "videos are"
                    } ready to be added to your searchable knowledge base.`
                );
            }


            analysisSection.scrollIntoView(
                {
                    behavior:
                        "smooth",

                    block:
                        "start",
                }
            );


        } catch (
            error
        ) {

            hideAnalysis();


            showMessage(
                "error",
                "Analysis Failed",
                error.message ||
                    "Something went wrong while analyzing the URL."
            );


        } finally {

            setAnalyzeLoading(
                false
            );
        }
    }
);


/* ============================================================
   URL INPUT
   ============================================================ */

youtubeUrl.addEventListener(
    "input",
    () => {

        const hasValue =
            youtubeUrl.value
                .trim()
                .length >
            0;


        clearBtn.classList.toggle(
            "hidden",
            !hasValue
        );
    }
);


/* ============================================================
   CLEAR URL
   ============================================================ */

clearBtn.addEventListener(
    "click",
    () => {

        youtubeUrl.value =
            "";

        clearBtn.classList.add(
            "hidden"
        );

        hideAnalysis();

        hideMessage();

        /*
         * Clear old playlist context.
         */
        try {

            localStorage.removeItem(
                "youtubeReviserCurrentVideos"
            );

            localStorage.removeItem(
                "youtubeReviserCurrentUrl"
            );

            localStorage.removeItem(
                "youtubeReviserCurrentTitle"
            );

            localStorage.removeItem(
                "youtubeReviserCurrentPlaylistId"
            );

        } catch {
            // localStorage is optional.
        }


        youtubeUrl.focus();
    }
);


/* ============================================================
   CLOSE MESSAGE
   ============================================================ */

closeMessageBtn.addEventListener(
    "click",
    hideMessage
);


/* ============================================================
   PROCESS BUTTON
   ============================================================ */

processBtn.addEventListener(
    "click",
    async () => {
        if (!currentAnalysis) {
            return;
        }

        const newVideos = getNewVideos();

        if (newVideos.length === 0) {
            showMessage(
                "success",
                "Nothing New",
                "All videos from this URL have already been processed."
            );
            return;
        }

        processBtn.disabled = true;
        processBtn.textContent = "Processing Videos...";

        showProcessingSection(newVideos.length);

        const processingItems = newVideos.map((video, index) =>
            createProcessingItem(video, index)
        );

        let completedVideos = 0;
        let failedVideos = 0;
        let jobResults = [];

        try {
            await startProcessStream(
                currentAnalysis.url,
                newVideos.map(video => video.video_id),
                (event) => {
                    if (event.type === "stage_progress") {
                        updatePipelineStage(event.stage, event);
                        if (event.message && progressStepText) {
                            progressStepText.textContent = event.message;
                        }
                    } else if (event.type === "step") {
                        if (progressStepText) {
                            progressStepText.textContent = event.step;
                        }
                    } else if (event.type === "video_status") {
                        const item = processingItems.find(
                            p => p.videoId === event.video_id
                        );
                        if (item) {
                            markProcessingItem(
                                item,
                                event.status,
                                event.message
                            );
                        }
                    } else if (event.type === "complete") {
                        jobResults = event.results || [];
                        const total = event.total || newVideos.length;
                        const succeeded = event.succeeded || 0;
                        const failed = event.failed || 0;

                        updatePipelineStage("complete", {});

                        if (progressMainHeading) {
                            progressMainHeading.textContent = "✓ Processing complete";
                        }
                        if (progressStepText) {
                            progressStepText.textContent = `${total} videos ready`;
                        }

                        if (completionSummary) {
                            completionSummary.classList.remove("hidden");
                            if (completionDetails) {
                                completionDetails.textContent =
                                    `${total} videos processed (${succeeded} successful, ${failed} failed)`;
                            }
                        }

                        if (failed === 0 && succeeded === newVideos.length) {
                            showMessage(
                                "success",
                                "Knowledge Base Updated",
                                `${succeeded} ${
                                    succeeded === 1 ? "video has" : "videos have"
                                } been successfully added to your searchable knowledge base.`
                            );
                        } else if (succeeded > 0) {
                            showMessage(
                                "warning",
                                "Processing Partially Complete",
                                `${succeeded} ${
                                    succeeded === 1 ? "video was" : "videos were"
                                } added successfully, but ${failed} ${
                                    failed === 1 ? "video could not" : "videos could not"
                                } be added.`
                            );
                        } else {
                            showMessage(
                                "error",
                                "Processing Failed",
                                "None of the selected videos could be added. Check the errors shown below."
                            );
                        }

                        if (currentAnalysis && Array.isArray(currentAnalysis.videos)) {
                            currentAnalysis.videos = currentAnalysis.videos.map(video => {
                                const resItem = jobResults.find(
                                    r => r.video_id === video.video_id
                                );
                                if (resItem && resItem.success === true) {
                                    return { ...video, already_saved: true };
                                }
                                return video;
                            });
                        }

                        updateStats({
                            ...currentAnalysis,
                            saved_videos:
                                currentAnalysis.videos?.filter(v => v.already_saved).length || 0,
                            new_videos:
                                currentAnalysis.videos?.filter(v => !v.already_saved).length || 0,
                        });

                        renderVideos(currentAnalysis.videos || []);
                        updateProcessButton(currentAnalysis);
                        saveCurrentAnalysis(currentAnalysis, currentAnalysis.url);

                        processBtn.textContent = succeeded > 0 ? "Processing Complete" : "Retry Processing";
                        processBtn.disabled = succeeded === newVideos.length;
                    } else if (event.type === "error") {
                        throw new Error(event.message || "Processing error occurred.");
                    }
                }
            );
        } catch (error) {
            if (progressStepText) {
                progressStepText.textContent = "Processing failed";
            }
            showMessage(
                "error",
                "Processing Failed",
                error.message || "Something went wrong while processing the videos."
            );

            processingItems.forEach(item => {
                if (item.status.textContent === "Waiting" || item.status.textContent === "Fetching transcript...") {
                    markProcessingItem(item, "failed", error.message || "Failed");
                }
            });

            processBtn.disabled = false;
            processBtn.textContent = "Retry Processing";
        }
    }
);


if (removePlaylistBtn) {
    removePlaylistBtn.addEventListener(
        "click",
        async () => {

            if (
                !currentAnalysis ||
                !currentAnalysis.playlist_id
            ) {
                return;
            }

            const playlistId =
                currentAnalysis.playlist_id;

            const confirmed =
                window.confirm(
                    "Are you sure you want to remove this playlist and its transcripts from the knowledge base?"
                );

            if (!confirmed) {
                return;
            }

            removePlaylistBtn.disabled =
                true;

            removePlaylistBtn.textContent =
                "Removing playlist...";

            try {

                const response =
                    await fetch(
                        `/api/playlist/${encodeURIComponent(playlistId)}`,
                        {
                            method: "DELETE",
                        }
                    );

                if (!response.ok) {

                    let message =
                        "Unable to remove playlist.";

                    try {
                        const data =
                            await response.json();

                        if (data.detail) {
                            message =
                                data.detail;
                        }
                    } catch {
                        // ignore
                    }

                    throw new Error(
                        message
                    );
                }

                // Clear storage
                localStorage.removeItem(
                    "youtubeReviserCurrentPlaylistId"
                );

                localStorage.removeItem(
                    "youtubeReviserCurrentVideoId"
                );

                localStorage.removeItem(
                    "youtubeReviserCurrentVideos"
                );

                localStorage.removeItem(
                    "youtubeReviserCurrentTitle"
                );

                showMessage(
                    "success",
                    "Playlist Removed",
                    "Playlist and its transcripts have been removed from your knowledge base."
                );

                hideAnalysis();

            } catch (error) {

                showMessage(
                    "error",
                    "Removal Failed",
                    error.message ||
                        "Something went wrong while removing the playlist."
                );

            } finally {

                removePlaylistBtn.disabled =
                    false;

                removePlaylistBtn.textContent =
                    "🗑 Remove Playlist";
            }
        }
    );
}