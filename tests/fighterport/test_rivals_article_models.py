import pytest
from echo_rivals2.article_models import mesh_reference, Unsupported


class Pak:
    def __init__(self):
        self.component=dict(SkeletalMesh=dict(ObjectPath='Content/Boulder.1'),
                            AttachParent=dict(ObjectName="SceneComponent'Default__Base:Root'",ObjectPath='Content/Base.2'))
    def props(self, pkg):
        if pkg=='Content/Child':
            return [dict(Type='BlueprintGeneratedClass',SuperStruct=dict(ObjectPath='Content/Base.0')),
                    dict(Name='Default__Child',Properties={})]
        assert pkg=='Content/Base'
        return [dict(Type='BlueprintGeneratedClass'),dict(Name='Default__Base',Properties=dict(ArticleMeshComponent=
            dict(ObjectName="SkeletalMeshComponent'Default__Base:Mesh'",ObjectPath='Content/Base.1'))),
            dict(Name='Mesh',Properties=self.component),dict(Name='Root',Properties={})]


def test_article_mesh_follows_default_renderer_inheritance_and_attachment():
    p=Pak();assert mesh_reference(p,'Content/Child')=='Content/Boulder'
    p.component['RelativeLocation']=dict(X=5)
    with pytest.raises(Unsupported,match='transform'):mesh_reference(p,'Content/Child')


def test_article_mesh_rejects_hidden_unresolved_and_cyclic_components():
    p=Pak();p.component['bVisible']=False
    with pytest.raises(Unsupported,match='visibility'):mesh_reference(p,'Content/Child')
    p=Pak();p.component['AttachParent']=dict(ObjectName="SkeletalMeshComponent'Default__Base:Mesh'",ObjectPath='Content/Base.1')
    with pytest.raises(Unsupported,match='cyclic'):mesh_reference(p,'Content/Child')
    p=Pak();p.component['SkeletalMesh']={}
    with pytest.raises(Unsupported,match='no explicit'):mesh_reference(p,'Content/Child')
