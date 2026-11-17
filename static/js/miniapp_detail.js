const auctionId = Number(
    window.location.pathname.split("/").filter(Boolean).pop()
);

const detailMessage = document.getElementById("detail-message");
const detailContent = document.getElementById("detail-content");
const bidForm = document.getElementById("bid-form");
const bidResult = document.getElementById("bid-result");
const submitButton = document.getElementById("submit-bid");

function safeText(value) {
    return String(value ?? "");
}

function showMessage(element, message, error = false) {
    element.textContent = message;
    element.classList.toggle("error", error);
}

function formatRemaining(seconds) {
    seconds = Math.max(0, Number(seconds) || 0);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${days}d ${hours}h ${minutes}m ${secs}s`;
}

async function loadAuction() {
    try {
        if (!Number.isInteger(auctionId) || auctionId < 1) {
            throw new Error("Invalid auction number.");
        }

        const response = await fetch(`/api/miniapp/auction/${auctionId}`);
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Auction could not be loaded.");
        }

        const item = data.auction;

        document.getElementById("product-title").textContent = item.title || "";
        document.getElementById("product-description").textContent =
            item.description || "No description available.";
        document.getElementById("product-code").textContent = item.code || "-";
        document.getElementById("service-fee").textContent =
            `${item.service_fee} Br`;
        document.getElementById("minimum-bid").textContent =
            `${item.minimum_bid} Br`;
        document.getElementById("bid-count").textContent =
            String(item.bids_count ?? 0);
        document.getElementById("remaining-time").textContent =
            formatRemaining(item.remaining_seconds);

        const image = document.getElementById("product-image");
        if (item.image_url) {
            image.src = item.image_url;
        } else {
            image.hidden = true;
        }

        const accountSelect = document.getElementById("telebirr-account");
        accountSelect.innerHTML = '<option value="">Choose an account</option>';

        for (const account of data.telebirr_accounts || []) {
            const option = document.createElement("option");
            option.value = account;
            option.textContent = account;
            accountSelect.appendChild(option);
        }

        const amountInput = document.getElementById("bid-amount");
        amountInput.min = item.minimum_bid;
        amountInput.placeholder = `Minimum ${item.minimum_bid} Br`;

        if (item.status !== "active" || Number(item.remaining_seconds) <= 0) {
            showMessage(detailMessage, "This auction is not currently accepting bids.", true);
            bidForm.hidden = true;
        } else {
            detailMessage.textContent = "";
        }

        detailContent.hidden = false;
    } catch (error) {
        showMessage(detailMessage, error.message, true);
    }
}

bidForm.addEventListener("submit", async event => {
    event.preventDefault();
    bidResult.textContent = "";

    if (!bidForm.reportValidity()) return;

    const payload = {
        bidder_name: document.getElementById("bidder-name").value.trim(),
        phone: document.getElementById("bid-phone").value.trim(),
        bid_amount: document.getElementById("bid-amount").value,
        telebirr_account: document.getElementById("telebirr-account").value,
        transaction_id: document.getElementById("transaction-id").value.trim()
    };

    submitButton.disabled = true;
    submitButton.textContent = "SUBMITTING...";

    try {
        const response = await fetch(
            `/api/miniapp/auction/${auctionId}/bid`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            }
        );

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Bid submission failed.");
        }

        showMessage(
            bidResult,
            "Bid submitted successfully. Payment status: PENDING. Please wait for administrator verification."
        );
        bidForm.reset();
    } catch (error) {
        showMessage(bidResult, error.message, true);
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = "SUBMIT BID";
    }
});

loadAuction();
