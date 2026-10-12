"""Settings: AI keys (kept in this session only) and how the AI is being used."""

from __future__ import annotations

import streamlit as st

from careerforge.ai.doctor import check_routes
from careerforge.ai.providers import Request
from careerforge.ui import state
from careerforge.ui.errors import explain
from careerforge.ui.text import md_escape


def render() -> None:
    st.title("Settings")
    st.subheader("AI", anchor=False)
    st.markdown(
        "AI is **optional**. Without it you still get the ATS check, insights, outreach drafts, the tracker, job "
        "search and CV/portfolio export. With it you also get AI-assisted reading, tailoring, cover letters and "
        "interview questions, all checked in code so nothing is invented.\n\n"
        "Free keys: [Google AI Studio](https://aistudio.google.com/apikey) (Gemini) and "
        "[Groq](https://console.groq.com/keys). Free plans have rate limits."
    )
    own = state.user_keys()
    with st.form("keys"):
        gemini = st.text_input(
            "Gemini API key", type="password", value=own.get("GEMINI_API_KEY", ""), autocomplete="off"
        )
        groq = st.text_input("Groq API key", type="password", value=own.get("GROQ_API_KEY", ""), autocomplete="off")
        saved = st.form_submit_button("Use my keys", type="primary")
    if saved:
        state.set_user_keys(gemini, groq)
        st.rerun()
    if own and st.button("Stop using my keys", key="keys-clear"):
        state.set_user_keys("", "")
        st.rerun()
    st.caption(
        "Keys are kept in this browser session's memory only: never written to disk, never logged, gone when you "
        "close the tab. Prefer a key with a low spending limit."
    )
    if not state.ai_configured():
        st.info("No AI key is configured. The app is running in basic mode.", icon=":material/info:")
        return
    left = state.ai_calls_left()
    if left is None:
        st.success("Using your own key: no shared limit applies.", icon=":material/check_circle:")
    else:
        st.info(f"Using this site's shared key: {left} AI actions left in this session. Add your own key for no limit.")
    if st.button("Test the AI connection", key="ai-test"):
        try:
            client = state.charge_ai()
            with st.spinner("Asking the model to say OK..."):
                done = client.complete(Request(system="Reply with the single word OK.", user="ping", max_tokens=8))
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
        else:
            st.success(f"Working. Answered by {done.provider} / {done.model}.", icon=":material/check_circle:")
    if st.button(
        "Check every model now", key="ai-models-check", help="One tiny request per model; counts as one AI action."
    ):
        try:
            client = state.charge_ai()
            with st.spinner("Asking each model..."):
                checks = check_routes(client)
        except Exception as exc:  # noqa: BLE001
            st.error(explain(exc), icon=":material/error:")
        else:
            working = [c for c in checks if c.ok]
            for c in checks:
                mark = ":material/check_circle:" if c.ok else ":material/cancel:"
                st.markdown(f"{mark} `{c.route}`: {'answered' if c.ok else md_escape(c.detail)} ({c.seconds:.1f}s)")
            if not working:
                st.error(
                    "No model answered. Check the key, the account's plan and region, and the reasons above.",
                    icon=":material/error:",
                )
            else:
                st.caption(
                    "Names change often. If the list above has old ones, nothing needs fixing: the app asks each "
                    "provider for its current models and skips the ones that fail."
                )
    try:
        client = state.ai_client()
    except Exception as exc:  # noqa: BLE001
        st.error(explain(exc), icon=":material/error:")
        return
    if client is not None:
        with st.expander("Models in use"):
            for route in client.routes:
                st.markdown(f"- {route}")
            for note in client.notes:
                st.caption(note)


if __name__ == "__main__":
    render()
