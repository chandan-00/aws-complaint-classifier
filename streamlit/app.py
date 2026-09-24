"""Section 43: a thin client for the deployed API.

The model is not here. This page only calls POST /complaints and GET /complaints/{id},
which is the point: the classifier is a service, and this is one of its callers.

Run:
    COMPLAINTS_API_URL=<terraform output invoke_url> \
    COMPLAINTS_API_KEY=<api key value> \
    streamlit run streamlit/app.py
"""
import os

import requests
import streamlit as st

TIMEOUT_S = 15
MIN_CHARS = 10  # mirrors the API's own validation, so the user hears about it sooner


def api_headers(api_key: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def submit(api_url: str, api_key: str, text: str) -> requests.Response:
    return requests.post(api_url, json={"text": text},
                         headers=api_headers(api_key), timeout=TIMEOUT_S)


def fetch(api_url: str, api_key: str, complaint_id: str) -> requests.Response:
    return requests.get(f"{api_url}/{complaint_id}",
                        headers=api_headers(api_key), timeout=TIMEOUT_S)


def show_result(resp: requests.Response) -> None:
    body = resp.json()
    if resp.status_code == 200:
        st.success(f"**{body['prediction']}**")
        col1, col2, col3 = st.columns(3)
        col1.metric("Confidence", f"{float(body['confidence']):.1%}")
        col2.metric("Inference", f"{float(body['inference_ms']):.0f} ms")
        col3.metric("Model", body["model_version"])
        st.caption(f"Processed at {body['processed_at']}")
    elif resp.status_code == 404:
        # The API cannot tell "still queued" from "never existed" without another lookup.
        st.info("Not scored yet — the complaint is queued or still being processed. "
                "Check again in a few seconds.")
    else:
        st.error(f"HTTP {resp.status_code}: {body}")


def main() -> None:
    st.set_page_config(page_title="Complaint classifier", page_icon="📨")
    st.title("CFPB complaint classifier")
    st.caption("DistilBERT, ONNX INT8, AWS Lambda — asynchronous via SQS")

    with st.sidebar:
        st.header("API")
        api_url = st.text_input("Invoke URL", os.environ.get("COMPLAINTS_API_URL", ""),
                                help="terraform -chdir=terraform output -raw invoke_url")
        api_key = st.text_input("API key", os.environ.get("COMPLAINTS_API_KEY", ""),
                                type="password")
    api_url = api_url.rstrip("/")

    text = st.text_area("Complaint narrative", height=160,
                        placeholder="I found an error on my credit report and want it corrected.")

    if st.button("Submit", type="primary", disabled=not api_url):
        if len(text.strip()) < MIN_CHARS:
            st.warning(f"Write at least {MIN_CHARS} characters.")
        else:
            try:
                resp = submit(api_url, api_key, text.strip())
            except requests.RequestException as exc:
                st.error(f"Could not reach the API: {exc}")
            else:
                if resp.status_code == 202:
                    st.session_state["complaint_id"] = resp.json()["complaint_id"]
                else:
                    st.error(f"HTTP {resp.status_code}: {resp.text}")

    complaint_id = st.session_state.get("complaint_id")
    if complaint_id:
        st.write(f"Queued as `{complaint_id}` — the API returned 202 and did not wait "
                 "for the model.")
        if st.button("Check result"):
            try:
                show_result(fetch(api_url, api_key, complaint_id))
            except requests.RequestException as exc:
                st.error(f"Could not reach the API: {exc}")

    if not api_url:
        st.info("Set the invoke URL in the sidebar (or COMPLAINTS_API_URL) to begin.")


main()
