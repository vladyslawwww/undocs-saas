import json

from flask import Flask, request

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook():
    print("\n" + "=" * 40)
    print(" RECEIVED FINISHED DATA FROM UNDOCS.AI")
    print("=" * 40)
    data = request.json
    print(json.dumps(data, indent=2))
    return "OK", 200


if __name__ == "__main__":
    print("Receiver listening on port 5001...")
    app.run(port=5001)
