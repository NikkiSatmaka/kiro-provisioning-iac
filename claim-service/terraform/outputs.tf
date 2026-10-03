# =============================================================================
# Outputs
# =============================================================================
#
# The one URL participants hit. A single Function URL serves both the GET claim
# page and the POST claim, so the claim-page URL *is* the function URL; a
# `claim_url` alias is provided for clarity in operator docs/QR generation
# (design: "outputs.tf: function_url").
# =============================================================================

output "function_url" {
  description = "Public Function URL for the claim service (GET = claim page, POST = claim)."
  value       = aws_lambda_function_url.claim_handler.function_url
}

output "claim_url" {
  description = "Alias of function_url — the URL to put behind the workshop QR code / short link."
  value       = aws_lambda_function_url.claim_handler.function_url
}
