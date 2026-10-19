import uvicorn
from web_app import app as fastapi_app

try:
    import gradio as gr
    # Mount Gradio onto our FastAPI app so Hugging Face Spaces detects the Gradio SDK,
    # while your custom YouTube Reviser UI runs directly at root /
    app = gr.mount_gradio_app(fastapi_app, gr.Blocks(), path="/_gradio")
except Exception:
    app = fastapi_app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)

