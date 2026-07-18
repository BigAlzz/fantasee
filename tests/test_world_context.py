from fantasee_server.models import GenerateRequest


def test_generation_request_preserves_world_and_voice_context():
    request = GenerateRequest(
        story_concept="Humans and Neanderthals share one winter valley.",
        world_context="Universe: Ice Age Valley\nRules: Both lineages have language and culture.",
        voice_assignments='[{"name":"Nara","voice":"Mia","style":"Intimate audiobook"}]',
    )

    assert "Ice Age Valley" in request.world_context
    assert "Nara" in request.voice_assignments
