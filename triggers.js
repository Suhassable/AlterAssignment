exports = async function(changeEvent) {
  const doc = changeEvent.fullDocument;

  // Ensure the document has an _id
  if (!doc || !doc._id) {
    console.log("No _id in the changed document.");
    return;
  }

  const cloudRunUrl = "https://embeddingsupdate-473189862617.asia-south1.run.app"; // Replace with your actual URL

  try {
    const response = await context.http.post({
      url: cloudRunUrl,
      body: JSON.stringify({ _id: doc._id }),
      headers: { "Content-Type": ["application/json"] }
    });

    console.log("Cloud Run response status:", response.status);
    console.log("Cloud Run response body:", response.body.text());
  } catch (err) {
    console.error("Error calling Cloud Run function:", err);
  }
};
