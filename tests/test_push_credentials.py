import json
from types import SimpleNamespace

import pytest

from radhouse.chat.push_credentials import GooglePushToken, SCOPE, TOKEN_URI


def credential_file(tmp_path, **changes):
    path = tmp_path / "synthetic-key.json"
    path.write_text(json.dumps({"type": "service_account", "project_id": "synthetic-project",
                               "token_uri": TOKEN_URI, **changes}))
    path.chmod(0o600)
    return path


def test_credential_validation_and_fixed_scoped_refresh(tmp_path, monkeypatch):
    recorded = []
    credential = SimpleNamespace(valid=False, token=None)
    def refresh(request):
        recorded.append(request(TOKEN_URI, method="POST", body=b"synthetic-oauth-assertion"))
        credential.valid = True
        credential.token = "synthetic-access-token"
    credential.refresh = refresh
    def create(info, scopes):
        assert info["project_id"] == "synthetic-project"
        assert scopes == [SCOPE]
        return credential
    monkeypatch.setattr("radhouse.chat.push_credentials.service_account.Credentials.from_service_account_info", create)
    token = GooglePushToken(credential_file(tmp_path), "synthetic-project")
    def transport(url, **kwargs):
        assert url == TOKEN_URI
        assert kwargs["allow_redirects"] is False
        assert 0 < kwargs["timeout"] <= 5
        return "synthetic-response"
    token.request = transport
    try:
        assert token() == "synthetic-access-token"
        assert token() == "synthetic-access-token"
    finally:
        token.close()
    assert recorded == ["synthetic-response"]


@pytest.mark.parametrize("changes", [{"project_id": "foreign"}, {"token_uri": "https://foreign.invalid/token"},
                                     {"type": "authorized_user"}])
def test_foreign_credential_configuration_refused(tmp_path, changes):
    path = credential_file(tmp_path, **changes)
    with pytest.raises(ValueError, match="invalid_push_credentials"):
        GooglePushToken(path, "synthetic-project")


def test_shared_or_symlink_credential_files_refused(tmp_path):
    path = credential_file(tmp_path)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="invalid_push_credentials"):
        GooglePushToken(path, "synthetic-project")
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="invalid_push_credentials"):
        GooglePushToken(link, "synthetic-project")
