package replica_set

import (
	"testing"

	mdbv1 "github.com/mongodb/mongodb-kubernetes-operator/pkg/apis/mongodb/v1"
	e2eutil "github.com/mongodb/mongodb-kubernetes-operator/test/e2e"
	"github.com/mongodb/mongodb-kubernetes-operator/test/e2e/mongodbtests"
	f "github.com/operator-framework/operator-sdk/pkg/test"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

func TestMain(m *testing.M) {
	f.MainEntry(m)
}

func TestReplicaSet(t *testing.T) {
	ctx := f.NewContext(t)
	defer ctx.Cleanup()
	if err := e2eutil.RegisterTypesWithFramework(&mdbv1.MongoDB{}); err != nil {
		t.Fatal(err)
	}

	mdb := e2eutil.NewTestMongoDB("mdb0")
	t.Run("Create MongoDB Resource", mongodbtests.CreateMongoDBResource(&mdb, ctx))
	t.Run("Config Map Was Correctly Created", mongodbtests.AutomationConfigConfigMapExists(&mdb))
	t.Run("Stateful Set Reaches Ready State", mongodbtests.StatefulSetIsReady(&mdb))
	t.Run("Stateful Set has OwnerReference", mongodbtests.StatefulSetHasOwnerReference(&mdb,
		*metav1.NewControllerRef(&mdb, schema.GroupVersionKind{
			Group:   mdbv1.SchemeGroupVersion.Group,
			Version: mdbv1.SchemeGroupVersion.Version,
			Kind:    mdb.Kind,
		})))
	t.Run("MongoDB Reaches Running Phase", mongodbtests.MongoDBReachesRunningPhase(&mdb))
	t.Run("Test Basic Connectivity", mongodbtests.BasicConnectivity(&mdb))
	t.Run("Test Status Was Updated", mongodbtests.Status(&mdb,
		mdbv1.MongoDBStatus{
			MongoURI: mdb.MongoURI(),
			Phase:    mdbv1.Running,
		}))
}
