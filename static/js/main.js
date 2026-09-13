// main.js — students will add JavaScript here as features are built

// ------------------------------------------------------------------ //
// AI autofill                                                         //
// ------------------------------------------------------------------ //

// Phone photos are often bigger than the upload limit (and Vercel's 4.5 MB request cap), so large
// or unusual images are shrunk to a JPEG in the browser before they're sent. If that fails the
// original file is sent and the server's type and size checks still apply.
const RECEIPT_MAX_SIDE = 2000;
const RECEIPT_SHRINK_OVER_BYTES = 1024 * 1024;
const RECEIPT_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"];

function localIsoDate() {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    return now.toISOString().slice(0, 10);
}

async function shrinkReceipt(file) {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, RECEIPT_MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob) {
        throw new Error("Could not encode the receipt");
    }
    return new File([blob], file.name.replace(/\.[^.]*$/, "") + ".jpg", { type: "image/jpeg" });
}

document.querySelectorAll("form[data-autofill]").forEach((form) => {
    const button = form.querySelector("button[type=submit]");
    const receipt = form.querySelector("input[type=file]");

    form.addEventListener("submit", () => {
        form.querySelector("input[name=today]").value = localIsoDate();
        button.dataset.label = button.textContent;
        button.textContent = button.dataset.busyText;
        button.disabled = true;
    });

    if (!receipt) {
        return;
    }

    receipt.addEventListener("change", async () => {
        const file = receipt.files[0];
        const supported = file && RECEIPT_TYPES.includes(file.type);
        if (!file || (supported && file.size <= RECEIPT_SHRINK_OVER_BYTES)) {
            return;
        }

        button.disabled = true;
        try {
            const smaller = await shrinkReceipt(file);
            if (!supported || smaller.size < file.size) {
                const transfer = new DataTransfer();
                transfer.items.add(smaller);
                receipt.files = transfer.files;
            }
        } catch {
            // Keep the original photo.
        } finally {
            button.disabled = false;
        }
    });
});

// Going back to the page can restore it from the browser's cache with the buttons still busy.
window.addEventListener("pageshow", (event) => {
    if (!event.persisted) {
        return;
    }
    document.querySelectorAll("form[data-autofill] button[data-label]").forEach((button) => {
        button.textContent = button.dataset.label;
        button.disabled = false;
    });
});
