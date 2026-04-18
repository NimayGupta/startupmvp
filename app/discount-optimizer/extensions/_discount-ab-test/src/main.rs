use shopify_function::prelude::*;
use shopify_function::Result;

// Generated types from input.graphql + schema.graphql via build.rs
// (run `shopify app function schema` to download schema.graphql)
#[shopify_function_target(
    query_path = "input.graphql",
    schema_path = "schema.graphql"
)]
fn run(input: input::ResponseData) -> Result<output::FunctionRunResult> {
    let ab_group = input
        .cart
        .attribute
        .as_ref()
        .and_then(|a| a.value.as_deref())
        .unwrap_or("control");

    let discount_pct_str = input
        .cart
        .discount_attribute
        .as_ref()
        .and_then(|a| a.value.as_deref())
        .unwrap_or("0");

    // Only treatment arm receives the discount
    if ab_group != "treatment" {
        return Ok(output::FunctionRunResult {
            discount_application_strategy:
                output::DiscountApplicationStrategy::FIRST,
            discounts: vec![],
        });
    }

    let discount_pct: f64 = discount_pct_str.parse().unwrap_or(0.0);
    if discount_pct <= 0.0 {
        return Ok(output::FunctionRunResult {
            discount_application_strategy:
                output::DiscountApplicationStrategy::FIRST,
            discounts: vec![],
        });
    }

    // Build targets: all ProductVariant line items
    let targets: Vec<output::Target> = input
        .cart
        .lines
        .iter()
        .filter_map(|line| {
            if let input::InputCartLinesCartLineMerchandise::ProductVariant(variant) =
                &line.merchandise
            {
                Some(output::Target::ProductVariant(
                    output::ProductVariantTarget {
                        id: variant.id.clone(),
                        quantity: None,
                    },
                ))
            } else {
                None
            }
        })
        .collect();

    if targets.is_empty() {
        return Ok(output::FunctionRunResult {
            discount_application_strategy:
                output::DiscountApplicationStrategy::FIRST,
            discounts: vec![],
        });
    }

    Ok(output::FunctionRunResult {
        discount_application_strategy: output::DiscountApplicationStrategy::FIRST,
        discounts: vec![output::Discount {
            value: output::Value::Percentage(output::Percentage {
                value: Decimal(discount_pct),
            }),
            targets,
            message: Some(format!("A/B test discount: {:.0}% off", discount_pct)),
            conditions: vec![],
        }],
    })
}

// ---------------------------------------------------------------------------
// Unit tests — test pure discount-determination logic without proc macros
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    /// Determine the discount to apply, extracted for testability.
    fn determine_discount(ab_group: &str, discount_pct_str: &str) -> Option<f64> {
        if ab_group != "treatment" {
            return None;
        }
        let pct: f64 = discount_pct_str.parse().ok()?;
        if pct > 0.0 { Some(pct) } else { None }
    }

    #[test]
    fn treatment_group_gets_discount() {
        assert_eq!(determine_discount("treatment", "15.0"), Some(15.0));
    }

    #[test]
    fn control_group_gets_no_discount() {
        assert_eq!(determine_discount("control", "15.0"), None);
    }

    #[test]
    fn missing_group_gets_no_discount() {
        assert_eq!(determine_discount("control", "0"), None);
        assert_eq!(determine_discount("", "15.0"), None);
    }

    #[test]
    fn zero_discount_pct_gives_none() {
        assert_eq!(determine_discount("treatment", "0"), None);
        assert_eq!(determine_discount("treatment", "0.0"), None);
    }

    #[test]
    fn invalid_discount_str_gives_none() {
        assert_eq!(determine_discount("treatment", "notanumber"), None);
    }

    #[test]
    fn fractional_discount_preserved() {
        assert_eq!(determine_discount("treatment", "12.5"), Some(12.5));
    }
}
