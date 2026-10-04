from recall import Kind, extract_claims, infer_kind, values_agree


def keys(text):
    return [(c.predicate, c.value.lower(), c.polarity) for c in extract_claims(text)]


def test_residence_variants():
    assert keys("I live in Toronto") == [("lives_in", "toronto", True)]
    assert keys("Actually, I moved to Berlin!") == [("lives_in", "berlin", True)]
    assert keys("I'm now living in Lisbon") == [("lives_in", "lisbon", True)]


def test_compound_statements_split():
    out = keys("I live in Toronto and work at Shopify")
    assert ("lives_in", "toronto", True) in out and ("works_at", "shopify", True) in out


def test_likes_multi_and_negation():
    out = keys("I love hiking, coffee and jazz")
    assert [v for p, v, _ in out if p == "likes"] == ["hiking", "coffee", "jazz"]
    assert keys("I don't like hiking anymore") == [("likes", "hiking", False)]
    assert keys("I hate cilantro") == [("likes", "cilantro", False)]


def test_past_tense_is_not_a_current_claim():
    assert extract_claims("I used to live in Paris") == []


def test_my_x_is_y_and_world_facts():
    assert keys("My favorite color is green") == [("favorite_color", "green", True)]
    c = extract_claims("The deadline is Friday")[0]
    assert (c.subject, c.predicate, c.value) == ("world", "deadline", "Friday")


def test_third_person():
    c = extract_claims("Priya lives in Mumbai")[0]
    assert (c.subject, c.predicate, c.value) == ("priya", "lives_in", "Mumbai")


def test_values_agree():
    assert values_agree("Berlin", "berlin, germany")
    assert not values_agree("at 9am", "at 10am")


def test_kind_inference():
    assert infer_kind("Remind me to call mum tomorrow") == Kind.EPHEMERAL
    assert infer_kind("I live in Oslo", extract_claims("I live in Oslo")) == Kind.IDENTITY
    assert infer_kind("I love jazz", extract_claims("I love jazz")) == Kind.PREFERENCE
    assert infer_kind("We met with the client yesterday") == Kind.EVENT


def test_negation_is_lifted_into_polarity():
    c = extract_claims("The public API is not rate limited")[0]
    assert (c.predicate, c.value, c.polarity) == ("public_api", "rate limited", False)
    c = extract_claims("The cache isn't enabled")[0]
    assert (c.value, c.polarity) == ("enabled", False)
