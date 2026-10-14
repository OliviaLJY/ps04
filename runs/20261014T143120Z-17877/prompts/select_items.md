# Editorial selection task

Apply the snapshotted editorial policy to every eligible item. Return exactly one JSON decision per input item, in input order, with `item_id`, `version_id`, `decision`, `reason`, and `piece_ids`.

Use `accept`, `reject`, or `defer`. Explain the claim-level evidence, relevance, freshness, incentive, novelty, and perspective—not the publisher's reputation or your confidence. Treat repeated reporting of one announcement as one underlying claim. Assign accepted items only to pieces where they can support a specific argument. Rejected and deferred items must have an empty `piece_ids` array. Never invent content that is absent from the retained evidence.
