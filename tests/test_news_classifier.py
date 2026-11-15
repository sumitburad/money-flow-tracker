import json
import pytest
from backend.news_classifier import (check_tag, classify_headlines, fallback_tag)


def news():
    return {"headline_id":"abc","title":"Federal Reserve announces new banking policy",
            "publisher":"Federal Reserve","url":"https://www.federalreserve.gov/"}


def test_schema_rejects_fabricated_names_and_numbers():
    tag={"headline_id":"abc","event_type":"central_bank","region":["US"],
         "affected":["S&P 500"],"direction":"unclear","horizon":"days",
         "novelty":"new","confidence":"low",
         "one_line_reason":"Federal Reserve banking policy headline is unconfirmed"}
    assert check_tag(tag,news(),["S&P 500"])==tag
    tag["affected"]=["Invented Company"]
    with pytest.raises(ValueError,match="unknown"):
        check_tag(tag,news(),["S&P 500"])
    tag["affected"]=[]
    tag["one_line_reason"]="Secret rate hiked 6.25 percent"
    with pytest.raises(ValueError,match="numerical"):
        check_tag(tag,news(),["S&P 500"])


def test_without_api_key_rules_are_not_claimed_ai():
    tagged,h=classify_headlines([news()],[{"name":"S&P 500"}],env={})
    assert tagged[0]["classification"]["classifier"]=="deterministic_rules_NOT_AI"
    assert h["model_classified"]==0 and h["no_ai_is_not_model_inference"]


def test_valid_model_is_accepted_but_direction_remains_unconfirmed():
    class R:
        content=b"{}"
        def raise_for_status(self): pass
        def json(self):
            return {"choices":[{"message":{"content":json.dumps({
               "headline_id":"abc","event_type":"central_bank","region":["US"],
               "affected":["S&P 500"],"direction":"supportive","horizon":"days",
               "novelty":"new","confidence":"low",
               "one_line_reason":"Policy may affect United States equity exposure"})}}]}
    class H:
        def post(self,url,headers,json,timeout):
            assert headers["Authorization"].startswith("Bearer ")
            assert json["messages"][0]["role"]=="system"
            return R()
    tagged,h=classify_headlines([news()],[{"name":"S&P 500"}],
                               env={"GROQ_API_KEY":"sample-secret"},http=H())
    assert tagged[0]["classification"]["direction"]=="unclear"
    assert tagged[0]["classification"]["classifier"]=="validated_model_json"
    assert h["model_classified"]==1
    assert "sample-secret" not in str(tagged)
