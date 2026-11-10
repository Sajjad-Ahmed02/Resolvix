function Home() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center">
      <h2 className="text-4xl font-bold text-gray-900">
        Welcome to Resolvix
      </h2>

      <p className="mt-4 text-gray-600">
        Your customer support platform starts here.
      </p>

      <div className="mt-6 rounded-lg bg-green-100 px-4 py-2 text-green-700">
        Frontend is running successfully!
      </div>
    </div>
  );
}

export default Home;